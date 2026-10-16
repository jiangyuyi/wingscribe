# 文档清单与整理记录

整理日期：2026-10-16。先盘点文档，再针对入口、配置、路径、识别工厂和安装器做静态核对；未通读或重构全部业务代码。

## 迁移与合并

| 原位置 | 去向或处理 |
| --- | --- |
| `docs/CONFIGURATION.md` | `docs/user/configuration.md` |
| `docs/PUBLIC_EVALUATION.md` | `docs/research/evaluation.md` |
| `docs/PUBLIC_EVALUATION_RESULTS_2026-08-18.md` | `docs/research/results-2026-08-18.md` |
| `docs/LOCATION_RESOLUTION.md` | `docs/reference/location-resolution.md` |
| `docs/PRIOR_RERANKING.md` | `docs/research/prior-reranking.md` |
| `docs/code_audit_2026-03-20.md` | `docs/archive/audits/code-audit-2026-03-20.md` |
| `docs/code_audit_progress_2026-03-23.md` | `docs/archive/audits/code-audit-progress-2026-03-23.md` |
| `docs/recognition_optimization_plan_2026-08-17.md` | `docs/archive/plans/recognition-optimization-2026-08-17.md` |
| `docs/recognition_optimization_progress_2026-08-18.md` | `docs/archive/progress/recognition-optimization-2026-08-18.md` |
| `.context/progress.md` | `docs/archive/progress/legacy-progress.md` |
| `docs/chatgpt_optimization_context_2026-08-17.md` | `docs/archive/conversations/chatgpt-optimization-2026-08-17.md` |
| `docs/chatgpt_optimization_context_2026-08-17.html` | `docs/archive/conversations/chatgpt-optimization-2026-08-17.html` |
| `鸟类识别优化` | `docs/archive/conversations/鸟类识别优化` |
| `docs/ARCHITECTURE.md` | 删除旧文件：重写为 docs/development/architecture.md，修正路径、模块与校对顺序 |
| `docs/NAS_SETUP.md` | 删除旧文件：中英文重复且 base_dir 过期，合并为 docs/user/nas.md |
| `docs/NAS_SETUP_zh.md` | 删除旧文件：合并为 docs/user/nas.md，改用绝对源目录 |
| `SOLUTION_Chinese_Taxonomy.md` | 删除旧文件：提取实际导入流程至 docs/user/taxonomy.md，移除不存在的修复脚本与过时计数 |
| `docs/installer-plan.md` | 删除旧文件：早期 CPU-only/PyInstaller 草案已被现有双安装器替代，使用 installer/README.md |
| `.github/plans/dual-installer-plan.md` | 删除旧文件：双安装器已经实现，旧 CUDA 11.8 计划删除，以构建脚本与构建指南为准 |
| `docs/云端识别与分离部署方案.md` | 删除旧文件：旧伪代码、Docker 与认证设计移除；实际接口整理至 docs/reference/recognition-api.md，未实现项转入 status.md |
| `docs/release-checklist-cpu.md` | 删除旧文件：并入 docs/development/release-checklist.md |
| `docs/release-checklist-gpu.md` | 删除旧文件：GPU 专项并入 docs/development/release-checklist.md |
| `installer/assets/README.md` | 删除旧文件：未引用的占位素材要求删除，实际图标来源写入 installer/README.md |
| `README.md` | 缩减为项目入口，操作步骤移入 user/；移除虚假仓库 URL、重复命令及未验证能力承诺 |
| `CLAUDE.md` | 收敛为 AGENTS 和现行文档导航 |
| `.context/activeContext.md` | 移除与最终 embedded Python 方案冲突的重建 venv 临时上下文，保留状态入口；历史演进见归档 progress |
| `.context/progress.md` | 原文归档，原位置只保留导航 |
| `installer/README.md` | 保留原位；纠正 iscc 版本参数、加入统一验收与实际素材说明 |
| `AGENTS.md`、`LICENSE` | 保持原位和原内容 |

## 其他目录的盘点边界

- `config/**/*.yaml` 中的配置说明仍随配置维护，本轮未改配置；`settings.yaml` 的原有用户修改完整保留。secrets 样例的遗留差异已明确写入配置指南和 status。
- `requirements*.txt`、`installer/version.txt`、词典 TXT/CSV 是机器读取输入，不作为重复文档删除。
- `data/species_check.txt`、`data/coverage_report.txt` 为数据/历史报告；`data/processed/test.txt` 为输出测试文件，均不作现行指南、不改动。
- `.test-cache-inaturalist/README.md` 为测试缓存自述，`.pytest_cache/`、`htmlcov/`、`evaluation_results/` 为生成物；保留、不纳入手写指南。
- `src/web/templates/*.html` 是应用模板；`venv/`、安装构建目录、第三方运行时中的说明/许可证属于依赖或生成物，不迁移。
- `.claude/`、`.deploy_config/`、`.codex-tmp/` 为工具/本地运行配置或临时内容，不公开其中配置和执行痕迹。
- 截图保留在 `docs/screenshots/`；AI 导出的 HTML 与配套资源按原字节整体归档。

## 核验发现

修正了 NAS base_dir、WS_HOST/WS_PORT、流水线密钥结构、源码仓库 URL、校对写回范围、文件模板变量以及 iscc 版本传递等说明。真实代码缺口集中在 [项目状态](../development/status.md)。

历史审计和研究结论仅调整归档标识与必要链接，不把旧测试数量冒充本次结果。原始对话未重写，不外网复核其内容。

## 验证范围

本次执行本地 Markdown 相对链接检查、旧现行路径引用检查、迁移前后原始资料 SHA-256 对照和 Git diff 空白检查。应用代码未改变，不运行识别、写照片、安装构建或全量业务测试。检查结果：89 个本地 Markdown 链接无失效，9 个现行 YAML 示例可解析，文中 Python 脚本入口均存在，56 个原始资料/用户配置文件 SHA-256 对照一致，`git diff --check` 通过。原始对话不改写，因此其内部外部链接及历史文本路径不纳入现行指南检查。
