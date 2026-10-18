# 架构与数据流

核对日期：2026-10-18。本文说明当前代码分工；后续想法见 [项目状态](status.md)，早期审计见 [档案](../archive/README.md)。

## 主要模块

| 位置（相对仓库根目录） | 职责 |
| --- | --- |
| `src/pipeline_runner.py` | `WingScribePipeline` 扫描、检测、质量检查、裁切、批量识别、归档 |
| `src/core/` | 检测器、质量评估器、裁切处理器 |
| `src/core/io/` | 文件访问、路径解析与生成、临时文件管理 |
| `src/recognition/inference_*.py` | 流水线使用的本地和旧式 API 识别器 |
| `src/recognition/cloud/`、`protocol.py`、`batch.py` | 统一请求协议、云适配器和批任务服务 |
| `src/metadata/` | AviList/旧 IOC 数据、SQLite、ExifTool 写入、地点解析 |
| `src/web/app.py` | FastAPI 入口、路由、人工校对逻辑 |
| `src/web/*_service.py` | 配置、任务、管理、分类查询、地点预览服务 |
| `src/web/path_helpers.py` | 多源原图和处理图的 Web 路径解析 |
| `src/evaluation/`、`scripts/evaluate_*.py` | 独立评测，不改变生产识别默认行为 |

## 自动处理

目录扫描 → 日期/地点解析 → YOLO 鸟体检测 → 质量模式判断 → 裁切 → 识别与 Top-K → 文件/元数据/SQLite。

样例配置选择 YOLO26n 与 BioCLIP2。`legacy_reject` 保留模糊过滤，`score_only` 记录质量不跳过，`disabled` 关闭计算；质量分不参与物种排序。注意 `legacy_reject` 且 `blur_threshold <= 0` 时也会跳过质量计算。

识别候选根据地区配置选择。并发处理后按候选集合批量识别；停止请求是协作式停止，已提交工作可自然结束。流水线的 `local/api/dongniao` 与统一 REST 工厂不是同一接口，不能把平台列表当作流水线模式列表。

## 人工校对

`POST /api/update_label` 读取照片和分类信息，必要时移动裁切文件，写裁切图和存在的原图元数据，然后提交人工标签与确认时间并更新物种统计。错误时会尝试回滚文件移动，但不提供文件、EXIF 和数据库之间的完整原子事务。

原图写回当前不检查流水线的 `write_back_to_source`。具体风险与后续事项集中在 [项目状态](status.md)。

## 数据与路径

SQLite 包含 `taxonomy`、`photos`、`scan_history` 及物种统计等结构。照片记录保留候选、自动/人工标签来源和可选质量数据。文件数据库热点操作采用短连接与写锁；部分兼容代码仍直接使用 `manager.conn`。

B4a 新增独立的 `src/storage/catalogue.py`，提供来源、原片版本、分析/检测与持久任务数据结构。它尚未接入扫描或应用启动；只在显式初始化时创建增量表，已有库需先备份，详见[原片与任务存储契约](asset-catalogue.md)。

源目录及输出目录使用绝对路径，内部参考文件按项目根目录使用；命令统一在根目录执行。Web 原图通过 `/raw/source-{index}/...` 对应多个源，处理图由 `/processed/...` 提供。

## 研究能力边界

- 地点解析仅有独立模块和 `POST /api/location/preview` 只读预览。
- 多视野融合和软先验在离线评测中使用，未接入默认流水线。
- BioCLIP 2.5 已注册为实验模型；配置样例仍使用 BioCLIP2。缺省回退与显式配置的差异见 [配置](../user/configuration.md)。
- 人工确认数据已可区分，但 prototype/kNN 和连拍排序仍属待实施方向。


## 应用实例与启动（B3d）

`src.web.app.create_app()` 显式创建 Web 应用，`app.state.runtime` 保存该实例的配置、路径、模板、ExifWriter 和 TaskManager。导入模块不读取个人配置，不初始化数据库或模型。数据库初始化在 lifespan 启动阶段执行，失败时仅开放设置入口。

识别工厂的配置和本地模型缓存、批任务服务也由各应用实例分别持有；后台照片任务使用该实例启动时的配置快照。保存新配置后仍需重启。退出时协作停止并等待照片任务，取消本实例识别批次，释放模型缓存引用；底层已经开始的推理无法强杀。

脚本入口仍为 `python src/web/app.py` 和 `python src/recognition_service.py`。直接使用 Uvicorn 时采用 `src.web.app:create_app --factory` 或 `src.recognition_service:create_app --factory`，不再提供导入即构建的模块级 `app`。

测试通过显式工厂和临时配置创建应用，不再在导入前替换配置加载器。实例隔离用于清晰的生命周期和测试，不意味着可以让两个实例同时处理同一数据库/输出目录；跨进程任务互斥留待 B4。
