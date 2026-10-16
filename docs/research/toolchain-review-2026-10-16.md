# 工具链重新调研与选择建议

调研日期：2026-10-16。范围：Windows 个人本地应用、NAS 照片、JPEG 鸟类识别与选片。以下分开标明现状、候选和待实测事项；“有更新版本”不代表“已经适配本项目”。

## 1. 建议总表

| 层次 | 当前仓库 | 建议 | 替换门槛 |
| --- | --- | --- | --- |
| 环境与依赖 | 无约束 requirements + 两套安装器清单 + 脚本硬编码 wheel | 引入 `pyproject.toml`、uv 锁文件、明确 CPU/CUDA 配置和开发/评测依赖组；安装器从锁定清单导出 | 干净环境解析、安装、自检和既有行为回归 |
| Python | 安装器固定 3.11.8，旧 venv 已无法运行 | 先保留可复现基线，单独验证有可分发 Windows runtime 的 3.13/3.14 候选 | PyTorch、OpenCLIP、OpenCV 等 wheel 齐全；embedded Python 自检通过 |
| PyTorch | CPU 2.4.1/torchvision 0.19.1；GPU 2.10.0/0.25.0/cu128 | 优先消除两条长期漂移分支，比较已知 GPU 基线与当前稳定候选，不一次全升 | CPU/CUDA 两种 profile 均可安装，目标 GPU 编码、速度/显存和预测回归达标 |
| 鸟体检测 | Ultralytics 8.4.14、YOLO26n、COCO bird 类 | 先保留 YOLO26n；同框架小模型规模对比，比盲目换框架更直接 | 真实小鸟/遮挡鸟召回、误框、耗时优于基线；同时明确分发许可 |
| 检测替代 | 未接入 | RT-DETR 官方实现作为有条件候选，不直接替换 | 部署成本与鸟体召回实测；单独核验代码和权重许可 |
| 物种识别 | OpenCLIP + BioCLIP2，2.5 实验 | 保留 BioCLIP2 默认基线，锁定 OpenCLIP 和模型 revision；2.5 继续受控对比 | 本地鸟片改善明显且资源成本可接受；避免只依据 CUB 数据 |
| JPEG 解码/区域计算 | Pillow + OpenCV | 保留；统一方向、色彩和缩放协议，原分辨率区域用于合焦分析 | EXIF 旋转、极大图、多源 JPEG、100% 预览坐标一致 |
| 选片算法 | 拉普拉斯/梯度加混合质量分 | 新建专用 FocusAssessment；经典局部指标为基线，PyIQA TOPIQ/MUSIQ 为实验候选 | 在成组、人工确认的鸟片上提高排序及失焦候选精度 |
| 元数据 | 自写 subprocess ExifTool 包装，同时声明 PyExifTool | 保留 ExifTool；统一读写服务，实验批量只读/常驻进程；去掉确无用途的重复封装依赖 | 相机标签兼容、进程生命周期、超时、Unicode 和吞吐测试 |
| 数据库 | sqlite3；依赖表却声明 SQLAlchemy | 保留 SQLite，明确仓储和迁移版本；本地存储，单一写入边界 | 迁移/回退、并发与中断恢复通过；没有证据需要 MySQL |
| Web | FastAPI/Jinja/Bootstrap，大量内联 JavaScript | 保留后端与页面入口，先抽离前端模块；单独建设选片交互区 | 键盘操作、同步缩放和长列表测试；有明确收益才增加 SPA 工具链 |
| 配置 | 原始 YAML dict，多个入口手动读取 | 使用已有 Pydantic 做统一 schema/默认值与校验；YAML 保留用户可编辑性 | 未配置可启动设置页；错误字段可定位；配置往返不丢字段 |
| 任务执行 | 内存 singleton + 线程池 + 多入口状态 | 本地有界队列、一个受控模型工作进程、持久化任务项 | GPU 不重复加载、取消/重试/崩溃恢复和长任务内存稳定 |
| Windows 发布 | Inno Setup + embedded Python | 保留打包方式，统一依赖来源、版本和缓存校验 | 干净 Windows、非管理员目录、中文路径、NAS、离线缓存验收 |
| 工程质量 | pytest、覆盖率；无常规 PR 测试门禁 | 保留 pytest，加 Ruff，接口边界逐步加类型检查，PR 自动验证 | 先检查新增/改动代码，避免一次全库格式化掩盖行为变更 |
| 分类学数据 | IOC 15.1 Excel、中文 CSV | 引入 taxonomy_version 和名称映射；评估 IOC 15.2/AviList 的后续迁移 | 历史标签、物种拆并、中文名和候选特征缓存均可追溯 |

## 2. 版本与升级顺序

本次官方 PyPI 页面已经可见 torch 2.14.1（2026-09-30），Ultralytics 搜索快照可见 8.4.158（2026-09-21）。它们仅是调研候选；Ultralytics 快照不保证是执行升级当天的最新版本。OpenCLIP、FastAPI 的具体目标版本应在依赖解析与回归后写入锁文件，不以网页抓取的动态“最新”值作安装命令。[PyTorch 发布信息](https://pypi.org/project/torch/)、[Ultralytics 发布信息](https://pypi.org/project/ultralytics/)、[OpenCLIP](https://pypi.org/project/open-clip-torch/)、[FastAPI](https://pypi.org/project/fastapi/)。

Python 官方 2026-10 发布记录列出 3.13.16 和 3.14.8 的二进制安装包；3.12 已进入只有安全更新的阶段，不能把“升级到最新版 3.12”直接等同于获得新的官方 Windows embedded runtime。建议试验 3.13，再视完整 wheel 支持评估 3.14；保留旧环境作为回归对照，不在本轮替换。[Python 官方发布记录](https://blog.python.org/2026/10/python-31022-31117/)、[Python 3.12 发布说明](https://www.python.org/downloads/release/python-31213/)。

uv 官方支持按 CPU/CUDA 使用指定 PyTorch 包索引及依赖来源，适合统一现有安装路径。运行时 profile 是显式选择，不根据开发机恰好安装的 torch 决定最终包内容。[uv 的 PyTorch 集成](https://docs.astral.sh/uv/guides/integration/pytorch/)。

升级顺序：先锁定可复现环境 → 非模型依赖 → Python/torch/torchvision/OpenCLIP 兼容矩阵 → 检测库版本 → 模型权重 → 选片模型。每一步记录安装、加载、固定图片预测、资源开销与回退版本。

FastAPI 官方建议固定通过测试的版本，让 FastAPI 选择兼容的 Starlette；因此不再手写互相独立的 FastAPI/Starlette 目标约束，但锁文件仍应记录最终解析版本。[FastAPI 版本指南](https://fastapi.tiangolo.com/deployment/versions/)。

`sqlalchemy`、`PyExifTool`、`transformers` 在 `src/`/`scripts/` 直接导入扫描中没有出现。前两项可审查删除；`transformers` 仍可能是模型/其他库的间接需求，必须依赖解析和运行验证后决定，不能只凭 grep 删除。

## 3. 模型选择

YOLO26 已有官方支持，换到另一种检测框架不是本轮必要条件。当前使用 COCO 整鸟检测，不能自动提供可靠鸟眼定位。官方通用 Pose 预训练权重的 17 个关键点针对人体，不能拿“支持 pose”当成“支持鸟眼”。[YOLO26](https://docs.ultralytics.com/models/yolo26)、[Pose 关键点定义](https://docs.ultralytics.com/tasks/pose/)。

若需要头部/眼部评分，应独立验证鸟类关键点数据和小型头部定位模型，或先支持人工指定区域。若检测许可不符合最终分发目标，再对比官方 RT-DETR 实现；不要通过换一个 YOLO 导出格式误以为许可要求消失。Ultralytics 官方提供 AGPL-3.0/Enterprise 路径，RT-DETR 仓库列为 Apache-2.0；具体组合和权重仍需分别核验。[Ultralytics 许可说明](https://www.ultralytics.com/license)、[RT-DETR 官方仓库](https://github.com/lyuwenyu/RT-DETR)。这是一项分发决策待办，不在本轮更改项目许可证。

BioCLIP 2.5 官方模型卡提供 OpenCLIP 加载方式；仓库既有评测在中国鸟类子集上的改善证据不足，不能因此强行替换 BioCLIP2。应固定 tokenizer、preprocess、模型 revision、候选物种版本和精度模式，使两次评测真正可比。[BioCLIP 2.5 模型卡](https://huggingface.co/imageomics/bioclip-2.5-vith14)、[本项目历史结果](results-2026-08-18.md)。

## 4. 选片与元数据

PyIQA 提供 TOPIQ、MUSIQ 等无参考图像质量模型，适合做实验对照。TOPIQ 论文使用语义引导关注局部失真；这些模型的总体质量目标不是“鸟眼是否准确合焦”，必须经过鸟片验证，不能直接输出“失焦概率”。先实验两个轻量可运行候选，不将整个研究工具箱默认装进用户包。[PyIQA](https://github.com/chaofengc/IQA-PyTorch)、[TOPIQ 论文](https://arxiv.org/abs/2308.03060)、[MUSIQ 论文](https://arxiv.org/abs/2108.05997)。

ExifTool 继续负责相机拍摄时间、子秒、方向、曝光参数及可用 MakerNotes。可试验 `-stay_open` 减少反复启动成本，但必须由单服务管理，处理超时和输出边界；AF 点只作为区域线索，不能证明最终像素合焦。[ExifTool 应用文档](https://exiftool.org/exiftool_pod.html)。

RAW 后续使用 rawpy/LibRaw 作为解码候选。rawpy 可提取内嵌预览，也可执行 RAW 后处理；两条输入的缩放、降噪和锐化不同，评分不可无条件混合。支持 RAW 必须覆盖导入、配对、预览、区域坐标、分析、标记和恢复全链路。[rawpy API](https://letmaik.github.io/rawpy/api/rawpy.RawPy.html)。

## 5. 本地存储、分类标准和部署

SQLite 足以作为当前个人图库索引。数据库、缩略图和分析缓存留在本地；NAS 只提供原片等文件。WAL 可改善读写并行，但官方明确不支持跨网络文件系统使用，因此不能把开启 WAL 当作 NAS 数据库的通用解决方案。[SQLite WAL](https://www.sqlite.org/wal.html)。

IOC/AviList 官方说明 IOC 15.2 是最终版本，分类体系正向 AviList 汇合。这比单纯把 Excel 文件名改成新版更值得规划：先加版本化 taxon 标识和 synonym/crosswalk，保留历史人工标签；涉及物种拆分时不能自动猜旧照片属于新种。[AviList 官方背景](https://www.avilist.org/about/)、[IOC 主名录](https://www.worldbirdnames.org/new/ioc-lists/master-list-2/)。

Windows 打包继续使用 Inno Setup 和独立运行时，不引入整套新桌面框架；Inno Setup 仍提供安装、版本文件比较和文件校验能力。问题在项目构建来源分叉，而非缺少另一种打包器。[Inno Setup 官方说明](https://jrsoftware.org/isinfo.php)。

非 NVIDIA 加速另行评估。ONNX Runtime 官方已经将 Windows DirectML 描述为维护阶段并推荐新项目关注 WinML；不过模型导出、OpenCLIP 文本编码和数值一致性仍需工程工作。首版保留 CPU/CUDA，不因工具存在就承诺 Radeon 后端可用。[ONNX Runtime Windows](https://onnxruntime.ai/docs/get-started/with-windows.html)。

## 6. 实施时的比较记录

每个候选记录：版本与下载来源、模型哈希、许可证、Python/torch/驱动、输入像素数、冷/热启动时间、每图 p50/p95、CPU RSS、峰值显存、成功率、模型准确率或选片排序指标。性能预算需结合用户实际机器和图库规模设定，本轮不虚构吞吐数字。

研发工具建议使用 Ruff 执行基础静态检查与格式检查，pytest 保留，类型检查逐步覆盖跨模块接口。[Ruff 官方文档](https://docs.astral.sh/ruff/)。额外工具必须减少维护分支或带来可测收益，不因新版本或热度而加入。
