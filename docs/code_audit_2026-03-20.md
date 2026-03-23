# WingScribe 代码审查记录（2026-03-20）

## 审查范围与依据

本次审查先阅读了仓库内的 `CLAUDE.md` 与 `README.md`，以确认工程目标、运行方式、模块边界和预期行为，然后对 `src/` 下的业务逻辑代码做了完整巡检，重点覆盖：

- `src/pipeline_runner.py`
- `src/web/app.py`
- `src/metadata/ioc_manager.py`
- `src/recognition/` 及 `src/recognition/cloud/`
- `src/core/` 与 `src/core/io/`
- `src/utils/config_loader.py`

同时执行了完整测试：

- `python -m pytest`
- 结果：`76 passed, 1 skipped`
- 但覆盖率仅 `16%`，关键业务模块基本未被测试覆盖

## 根据文档梳理出的当前架构

从 `CLAUDE.md` 与 `README.md` 看，当前系统的设计意图是清晰的：

1. `pipeline_runner.py`
   作为主编排层，负责扫描、去重、检测、裁切、识别、写元数据、落库与归档。

2. `core/`
   承载图像检测、质量判定、裁剪，以及路径解析和输出路径生成。

3. `recognition/`
   负责本地 BioCLIP 与多个云端识别平台的抽象、协议和批量识别逻辑。

4. `metadata/`
   负责 SQLite 数据管理与 ExifTool 元数据写入。

5. `web/app.py`
   既提供页面，也直接承载大量 API、配置管理、任务管理和文件服务逻辑。

整体方向没有问题，但实现层已经出现了几类明显的结构性债务：

- 编排层、状态层、持久层和 Web 层相互穿透
- 路径约定在“源目录”和“输出目录”之间不一致
- 多线程逻辑依赖共享可变状态
- 配置/密钥读取约定与文档不一致
- 关键流程几乎没有自动化测试保护

## 关键问题

### P0：批量识别上下文在多线程下会串批，导致候选物种集合错用

位置：

- `src/pipeline_runner.py:565-603`

问题说明：

`process_image()` 在多线程中共享 `self.batch_buffer` 与 `self.current_candidate_labels`。代码自己已经写了 “This is risky if threads mix” 的注释，但实际仍然把不同地点/不同候选集的图片塞进同一个批次，并直接覆盖全局候选标签。

这会带来两个结果：

- 同一批次里的 crop 可能使用了错误的候选物种列表识别
- 识别结果会受任务执行顺序影响，表现为偶发错标，且难以复现

这不是代码风格问题，而是业务正确性问题，建议列为第一优先级修复。

### P0：Web 层把处理后图片错误地当作源图目录下的文件来解析和读取

位置：

- `src/web/app.py:315-355`
- `src/web/app.py:876-881`

问题说明：

`/processed/...` 路由、`resolve_processed_web_path()`、`update_label()` 对 `photos.file_path` 的处理都默认使用 `source_dir` 还原绝对路径，而不是 `output.root_dir`。

但流水线里处理后图片实际是保存到 `output.root_dir` 的，且数据库里存的是相对 `source_dir` 的相对路径并不可靠。结果是：

- 已处理图片的 Web 预览和下载路径在目录不重叠时会直接失效
- 修改标签时，重命名/移动处理图可能找不到真实文件
- 路径存储约定被“源目录”和“输出目录”两套逻辑混用

这也是业务正确性问题，建议尽快统一“原图路径”和“处理后路径”的存储/解析规则。

### P0：云平台密钥配置与 README 约定不一致，云识别基本不可用

位置：

- `src/utils/config_loader.py:100-117`
- `src/recognition/cloud/factory.py:115-120`
- `src/recognition/cloud/huggingface.py:48-58`
- `README.md:423-442`

问题说明：

README 明确要求把云端密钥写在 `config/secrets.yaml` 的 `cloud:` 段下；云识别器本身也从 `config["cloud"]` 读取配置。

但 `load_config()` 只把 `secrets.yaml` 中的 `recognition.api` 和 `recognition.dongniao` 合并回配置，完全没有合并 `cloud` 段。

结果是：

- HuggingFace / ModelScope / 阿里云 / 百度等云识别器无法从 `secrets.yaml` 获得配置
- 文档与代码行为不一致
- 用户按 README 配完后仍会在运行时收到“未配置 token”的错误

这是配置层面的断链，优先级应与主流程正确性同级。

### P1：`IOCManager` 共享单一 SQLite 连接，并在多线程流水线中直接复用

位置：

- `src/metadata/ioc_manager.py:16`
- `src/pipeline_runner.py:540-550`
- `src/pipeline_runner.py` 中多个线程任务会继续使用 `self.db`

问题说明：

虽然连接用了 `check_same_thread=False`，但这并不等价于“线程安全”。当前实现把一个长生命周期 SQLite 连接挂在 `IOCManager` 实例上，并在多个线程的 `process_image()`、归档和统计更新过程中直接访问。

风险包括：

- 写入与查询交错时出现锁争用或间歇性失败
- 连接状态异常时污染整次任务
- 数据层无法独立演进为事务边界清晰的 Repository/Service

建议改为“短连接/连接工厂 + 显式事务”，至少把写路径集中在单线程归档阶段。

### P1：标签修正接口先改数据库，再做文件移动和 EXIF 写入，容易产生不一致状态

位置：

- `src/web/app.py:887-889`
- `src/web/app.py:961-1068`

问题说明：

`/api/update_label` 先更新数据库，再尝试重命名处理图、更新处理图 EXIF、更新原图 EXIF。只要任一步失败，就会出现：

- 数据库中的物种已经变更
- 处理图文件却仍停留在旧路径或旧名称
- EXIF 可能只更新了一部分文件

这是典型的跨资源操作缺少补偿/事务编排问题。建议改成：

- 先准备所有目标路径和元数据
- 完成文件系统操作
- 最后提交数据库更新
- 或者采用“任务式补偿”策略

### P1：`web/app.py` 单文件过大，路由、配置、任务、文件服务和业务逻辑严重耦合

位置：

- `src/web/app.py`，约 1400+ 行

问题说明：

当前 `web/app.py` 同时承担：

- 应用启动与生命周期
- 后台任务管理
- 图片列表页/管理页
- 分类树与统计 API
- 标签修正业务
- 配置读取/保存/重启
- Tk 文件对话框
- 静态文件服务

这会导致：

- 任一功能改动都容易影响整体启动流程
- 业务逻辑难以被单测覆盖
- “页面控制器”和“领域逻辑”无法分层

这属于结构性问题，不必一次性重写，但应拆成至少 4 个模块：`routes`、`services`、`tasks`、`config_ui`。

### P1：独立识别服务的根路径计算错误，配置文件路径大概率读错

位置：

- `src/recognition_service.py:13-35`

问题说明：

`BASE_DIR = Path(__file__).parent.absolute()` 指向的是 `src/`，随后却读取 `BASE_DIR / "config" / "settings.yaml"`，即 `src/config/settings.yaml`。

仓库真实配置目录是项目根的 `config/`，不是 `src/config/`。这意味着独立识别服务很可能在默认启动方式下找不到配置。

同时它还与 `src/web/routes/recognition.py` 重复维护了平台列表与接口逻辑，后续容易产生双份行为漂移。

### P2：任务停止能力名存实亡

位置：

- `src/web/app.py:44-55`
- `src/web/app.py:176-179`

问题说明：

`TaskManager.should_stop` 被设置了，但流水线中没有消费这个标记，`lifespan` 关闭时调用 `task_manager.stop()` 也不会真正中断处理。

这会给用户造成“支持停止”的错觉。要么真正把取消信号下沉到扫描和处理循环里，要么去掉该状态，避免伪能力。

### P2：主流程里存在未收敛的临时实现和注释式逻辑

位置：

- `src/pipeline_runner.py:576-603`
- `src/core/detector.py:142-143`
- `src/web/routes/recognition.py:41-52`

表现：

- 以 `pass` 留空的“复杂逻辑待处理”
- 调试入口中残留 `print`
- API Key 校验直接放行，并带有 TODO

这些点单看都不大，但累积起来说明代码里仍有“先跑通再说”的路径没有回收，建议在第一轮优化时统一清理。

## 业务逻辑中存在的冗余与重复

### 1. CUDA 稳定性检查重复实现

位置：

- `src/core/detector.py`
- `src/recognition/inference_local.py`

同一类逻辑重复维护两份，后续一旦调整回退策略，很容易出现检测器和识别器行为不一致。

### 2. 平台列表与识别 API 描述重复维护

位置：

- `src/web/routes/recognition.py`
- `src/recognition_service.py`

平台元信息重复定义，且已经有独立识别服务与 Web 内嵌路由两套入口，后续新增平台时极易漏改。

### 3. 路径解析与绝对/相对路径转换散落多处

位置：

- `pipeline_runner.py`
- `ioc_manager.py`
- `web/app.py`

相同概念被不同模块以不同规则解释，是当前路径问题频出的根源。

## 测试与质量现状

虽然 `pytest` 当前全绿，但测试覆盖率暴露出一个更真实的情况：

- `src/web/app.py` 覆盖率 `0%`
- `src/pipeline_runner.py` 覆盖率 `7%`
- `src/metadata/ioc_manager.py` 覆盖率 `15%`
- 云识别模块与批处理模块几乎都是 `0%`

也就是说，测试主要覆盖了工具类和局部函数，而最核心的业务编排、Web 写路径和云识别配置没有自动化保护。这也是为什么当前一些“文档和代码不一致”的问题没有被测试发现。

## 模块化优化计划

建议按三个阶段推进，而不是一次大改。

### 阶段一：修正确性问题

目标：先消除错标、错路径、错配置这类直接影响结果正确性的风险。

建议项：

1. 重构流水线批处理模型
   - 取消全局 `current_candidate_labels`
   - 将 batch 按上下文显式分桶，或者串行化识别阶段
   - 为“多地点混合批次”补单测

2. 统一路径模型
   - 数据库中明确区分 `original_path` 与 `processed_path`
   - 相对路径分别相对各自根目录存储
   - `resolve_processed_web_path()` 与 `/processed` 路由改为基于 `output.root_dir`

3. 修复 `load_config()` 的密钥合并
   - 支持 `cloud` 段的递归合并
   - 为所有云平台增加配置加载测试

4. 重做 `/api/update_label` 的执行顺序
   - 先准备变更
   - 文件操作和 EXIF 成功后再提交 DB
   - 失败时返回明确错误并保持原状态

5. 修复 `recognition_service.py` 的项目根目录解析

### 阶段二：拆分结构，收口职责

目标：让代码可维护、可测试，而不是继续把复杂度堆进单文件。

建议项：

1. 拆分 `web/app.py`
   - `web/routes/photos.py`
   - `web/routes/admin.py`
   - `web/routes/config.py`
   - `web/services/photo_service.py`
   - `web/services/config_service.py`
   - `web/tasks/pipeline_task.py`

2. 为数据层增加连接工厂
   - `IOCManager` 不持有长连接
   - 读写接口改为短事务
   - 统计更新从请求链路中解耦

3. 提取共享基础设施
   - 路径解析/路径存储策略统一到一个 `PathService`
   - CUDA 检查逻辑统一到一个工具模块
   - 平台元信息统一成单一注册表

### 阶段三：补测试与可观测性

目标：让后续重构不再“靠人工回归”。

建议项：

1. 为流水线补集成测试
   - 多线程批处理
   - 多地点/多候选集识别
   - 去重与低置信度分支

2. 为 Web API 补测试
   - `/api/update_label`
   - `/api/pipeline/start_by_folders`
   - `/api/config/save`
   - `/api/recognition/*`

3. 为配置系统补测试
   - `settings.yaml + secrets.yaml` 合并
   - 首次运行空配置
   - 错误路径和迁移场景

4. 日志与审计
   - 批次 ID、图片 ID、目标路径、识别平台进入结构化日志
   - 标签修正记录补操作日志

## 建议的实施顺序

如果下一步准备开始改代码，建议按下面顺序推进：

1. 修 `cloud` 配置合并和 `recognition_service.py` 根路径问题
2. 修 processed 路径解析与 `/api/update_label` 的路径/事务问题
3. 重构流水线批处理上下文
4. 拆 `web/app.py`
5. 补关键测试

## 新观察到的回归线索

在本地手动复核中，用户反馈 `processing.device=auto` 启动后当前会回落到 CPU，而此前预期是可自动使用 GPU。

这条问题暂时先记录，不在当前测试补强批次里直接处理，避免把已经稳定的路径再次放大修改面。后续排查时建议优先检查：

- `src/core/detector.py` 的 `_check_cuda_stable()`
- `src/recognition/inference_local.py` 的 `_check_cuda_stable()`
- `auto` 模式下模型初始化与异常回退日志
- 最近变更后实际加载到的 `torch` / CUDA 环境与启动日志

## 当前测试推进记录

截至当前批次，已经补上的自动化覆盖主要包括：

- `config_loader` 对 `settings.yaml + secrets.yaml` 的递归合并
- `IOCManager` 的原图/处理图分离路径存储
- `pipeline_runner` 的候选标签隔离，避免多线程串批
- `/api/update_label` 的文件/EXIF/数据库一致性
- `resolve_processed_web_path()` 的 processed 根目录解析
- `/api/config/save` 的嵌套字段写入、类型转换、`db_path` 变更重启判断
- `/api/recognition/*` 的基础错误映射与批量参数边界
- `TaskManager` 与 `/api/pipeline/start*` 的启动、重复启动拦截、参数透传

当前仍然明确未完成、后续不要遗漏的部分有：

- `src/recognition/batch.py` 的任务状态流转、取消、清理、结果聚合测试
- `/api/pipeline/folders` 与 `_build_folder_tree()` 的目录过滤/懒加载测试
- `src/recognition_service.py` 的独立服务入口测试
- `IOCManager` 更多读写接口与并发/连接边界测试
- `processing.device=auto` 回落到 CPU 的排查与回归保护

补测试过程中还观察到一个路径一致性细节：

- `web/app.py` 里的目录树接口在 Windows 下会返回“绝对路径前半段保留反斜杠、追加子目录时使用 `/`”的混合分隔符路径
- 这不会立刻阻断当前功能，但属于后续可以顺手统一的输出规范问题

## auto 模式排查结论补充

本轮进一步排查后，`processing.device=auto` 当前回落到 CPU 的直接原因已经比较明确：

- `src/pipeline_runner.py` 仍然会把 `processing.device` 原样传给 `BirdDetector` 和 `LocalBirdRecognizer`
- `src/core/detector.py` 与 `src/recognition/inference_local.py` 这一轮并没有发生影响 GPU 选择逻辑的代码改动
- 当前环境执行 `python -c "import torch; ..."` 的实际结果显示：
  - `torch.__version__ = 2.10.0+cpu`
  - `torch.cuda.is_available() = False`
  - `torch.version.cuda = None`
  - `torch.cuda.device_count() = 0`

这说明现在的 `auto -> CPU` 更像是“当前 Python 解释器 / PyTorch 安装已经变成 CPU 版”，而不是本轮业务代码把 GPU 路径关掉了。也就是说，GPU 回退现象更偏向运行环境漂移问题，而不是本次代码修复直接引入的逻辑回归。

## 结论

当前工程“功能面”已经很完整，文档也写得比较清楚，但核心业务层存在几处会直接影响正确性的实现债务，尤其是：

- 多线程批处理共享状态
- processed 路径模型错误
- 云端 secrets 配置没有真正接上
- 标签修正缺少跨资源一致性保护

这些问题解决后，系统稳定性会明显提升；随后再做 `web/app.py` 与数据层拆分，维护成本会下降很多。
