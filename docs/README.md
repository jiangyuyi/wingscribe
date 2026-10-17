# 文档总览

现行文档核对日期：2026-10-16。核对对象是本地源码、配置样例和构建脚本；不意味着重新完成云服务联调、模型评测或安装包验收。

## 按用途阅读

| 用途 | 文档 |
| --- | --- |
| 安装、启动、首次处理、排错 | [安装与使用](user/getting-started.md) |
| 配置字段、路径与写回行为 | [配置指南](user/configuration.md) |
| 网络照片目录 | [NAS 设置](user/nas.md) |
| AviList 名录与中文显示名 | [分类数据](user/taxonomy.md) |
| 模块职责与数据流 | [架构](development/architecture.md) |
| 当前能力、实现缺口、后续事项 | [项目状态](development/status.md) |
| 是否重写与分阶段改造 | [工程评估与改造计划](development/modernization-plan-2026-10-16.md) |
| 当前批次与验证结果 | [实施记录](development/execution-log.md)、[锁定开发环境](development/environment.md) |
| 工具升级与替换选择 | [工具链调研](research/toolchain-review-2026-10-16.md) |
| JPEG 合焦选片与后续 RAW | [选片功能方案](research/focus-culling-plan.md) |
| 开发、测试与文档维护规则 | [贡献指南](development/contributing.md) |
| Windows 构建与验收 | [安装器构建](../installer/README.md)、[统一验收清单](development/release-checklist.md) |
| 识别服务、云配置和接口限制 | [识别 API](reference/recognition-api.md)、[后端验证状态](development/recognition-backends.md) |
| 地点词典和只读预览 | [地点标准化](reference/location-resolution.md) |
| 模型实验、复现命令与结果 | [评测指南](research/evaluation.md)、[历史结果](research/results-2026-08-18.md)、[软先验](research/prior-reranking.md) |
| 查阅早期决策或 AI 讨论 | [历史档案](archive/README.md) |
| 查找旧文件的新位置 | [文档清单与迁移记录](maintenance/document-inventory.md) |

## 目录与维护约定

- `user/`：给使用者的操作说明。
- `reference/`：接口、数据格式和能力边界。
- `development/`：开发、当前待办和发布流程。
- `research/`：实验方法与带日期的结果，明确生产接入边界。
- `archive/`：不可作为当前任务指令的历史证据。
- `maintenance/`：文档整理和核验记录。
- `screenshots/`：现有界面截图。

根目录只保留项目入口、许可证和工具约定；安装器构建说明留在 `installer/`，便于与构建脚本一起维护。`AGENTS.md` 为协作约定，`CLAUDE.md` 和 `.context/` 只提供入口，不再复制架构或维护另一套“当前进度”。

同一事实只指定一个维护位置：配置字段在配置指南，当前缺口在项目状态，实验数字在日期化结果。历史测试数量和性能数字必须保留原日期，不更新成未经执行的新结果。
