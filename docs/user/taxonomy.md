# AviList 名录与中文显示名

WingScribe 3.0.2 的默认候选名录使用 **AviList v2026**，共 11,172 种。来源为 [AviList 官方发布](https://www.avilist.org/checklist/v2026/)，许可 CC BY 4.0；完整引用、来源文件 SHA-256、转换说明和中文名来源见 `data/references/avilist-v2026.json`。只导入 species 层级，不把属或亚种作为识别候选。3.0.1 安装版使用 v2025b，须更新程序并显式迁移已有库。

`data/references/avilist-v2026.csv` 是新的固定版本名录；旧2025b CSV及manifest保留供复核和迁移。新空库由流水线或系统重置入口初始化；已有非空库不会在启动时被静默替换，需要执行显式迁移。

```yaml
paths:
  db_path: "data/db/wingscribe.db"
  taxonomy_catalogue_path: "data/references/avilist-v2026.csv"
```

未设置 `taxonomy_catalogue_path` 时使用项目内上述默认文件。旧 `ioc_list_path` 不再控制新候选集，但保留旧 IOC 文件作为名称来源与研究材料。禁止用旧 IOC 导入覆盖已经版本化的 AviList 库。

## 中文名与历史标签

官方2026扩展XLSX没有中文名列。本次10,941种沿用IOC15.1同学名中文显示别名，41种沿用2025b中相同Avibase概念ID的中文显示别名，190种以学名显示。目科属中文显示名来自仓库现有映射CSV。它们均不是AviList官方中文译名，映射文件中缺少中文时显示拉丁名。官方Explorer支持其他来源的多语言名称，本批不把该独立名称来源混入工作簿转换。

**同学名不等于分类范围相同。** `taxonomy_provenance` 记录 Avibase 标识、版本和中文显示名来源；`taxonomy_legacy_review` 将旧名称列为 `same_name_unverified` 或 `unmatched`，均不代表已完成分类概念对应。不猜测拆分、合并或更名后的旧照片归属。

本次采用低成本保留方式：旧名录完整留在 `taxonomy_legacy`，旧照片的标签和人工确认信息不变，`photos.taxonomy_version` 标为 `legacy-unversioned`。后续重新识别新增记录，或人工重新选择物种，才记录当前名录版本。旧照片仍可能按同学名出现在新分类树中，但这种显示关联不是已核实的历史分类迁移。

3.0.2 的中国候选使用 Avibase 的 AviList 2026 地域清单：CN、台湾、香港、澳门并集共 **1,539 种**，保留来源中的罕见/迷鸟记录。名单以概念ID精确关联全球名录，运行时离线校验版本和固定摘要；旧 `china_bird_list.txt` 不再决定候选，也不能只修改版本标签继续使用。来源与完整差异见[审计报告](../research/china-avilist-2026-audit.json)。Avibase 地域数据来源说明与 AviList 的 CC BY 许可分别记录，不能混为同一授权。

`auto` 保持原有简单规则：原图地点文本命中国外名称词典任一词时使用全球11,172种，否则（包括空白或Unknown）使用中国1,539种；`china` 固定中国，`global` 或旧null使用全球。圈养海外鸟种或特殊地点可手动选全球。候选在推理前限定，不是删除全球Top-K中的结果；范围变小会改变归一化分数，不代表准确率已提升，原阈值不自动调整。中国名单缺失、损坏或版本不匹配会明确报错，不再静默回退全球。

已有照片标签与人工校对不变，新候选签名会使旧全球分析无法直接作为中国结果复用。旧结果复查仅提供只读预览：`python -m scripts.preview_regional_recheck --database data/db/wingscribe.db --output data/backups/regional-preview.json`。报告按分析历史计数；名单外名称可能是历史旧名，不等于识别错误。确认日期/目录后再安排重识别，不自动覆盖人工结果或清理旧归档。版本变化见[3.0.2 发布说明](../releases/3.0.2.md)。

安装版自带的隔离Python不通过 `-m scripts` 查找入口；请从安装目录使用 `python/python.exe scripts/preview_regional_recheck.py --database data/db/wingscribe.db --output data/backups/regional-preview.json`，有自定义数据库路径时替换为实际文件。已迁移到2026的安装库还应将配置中的 `taxonomy_catalogue_path` 指向2026 CSV，不能继续保留指向2025b的显式路径；版本不匹配时中国筛选会明确拒绝。

## 迁移与回退

关闭正在使用该数据库的应用和流水线后，在锁定环境中执行。数据库必须放在本机；照片可在 NAS。

```powershell
# 只读预览
python scripts/migrate_avilist.py --database data/db/wingscribe.db --report data/backups/avilist-preview.json

# 应用：先备份，再在事务中替换活动名录，保留全部照片标签
python scripts/migrate_avilist.py --database data/db/wingscribe.db --apply --backup-dir data/backups --report data/backups/avilist-migration.json
```

以上用于旧未版本化数据库的首次迁移。已使用2025b的库需要显式授权版本升级。安装版请从安装目录执行，将命令中的 `python` 换成 `.\python\python.exe`，并用设置中的实际数据库路径替换示例：

```powershell
# 先关闭该库的后台服务；不要在识别或选片任务运行中迁移。
python scripts/migrate_avilist.py --database data/db/wingscribe.db --upgrade-from AviList-v2025b --apply --backup-dir data/backups --report data/backups/avilist-2026-upgrade.json
```

程序共享识别/选片的库锁，运行或尚未恢复的中断任务会阻止迁移。2025b活动内容必须与固定旧发布一致；全局升级前备份，事务中归档旧名录、旧manifest和来源表到`taxonomy_release_history`。不重写photos、人工校对或分析历史；旧名字从新分类消失时，历史标签仍保留，后续重识别/人工校对另行处理。

报告记录版本、物种数量、保留照片数、备份路径及旧名称复核清单。相同内容再次执行不会重复导入；仅显式支持2025b→2026，其他版本拒绝。发布文件校验不符会拒绝加载，不能手动编辑CSV或仅重算manifest绕过固定发布摘要。

`pre_schema_backup` 是结构调整前的完整数据库备份；`backup_path` 是活动名录替换前的事务一致性备份。恢复时先关闭应用，保留当前数据库副本，再将报告中的 `pre_schema_backup` 复制回原数据库路径。备份包含照片索引，建议另行保存到可靠位置；Git 不包含 `data/backups/`。照片文件没有被迁移命令修改。

## 重新生成发布文件

下载manifest中固定的官方2026 XLSX，使用相同IOC中文名工作簿、目科属映射和旧2025b固定CSV，调用 `scripts/migrate_avilist.py --build-from <官方文件> --ioc-names <IOC中文文件> ...`。源文件哈希不符会拒绝构建；当前源哈希是对官方链接下载文件的本地固定摘要，并非官方独立发布签名。此选项只重新生成名录，是否改库仍由`--apply`决定。生成文件和manifest必须一起审核、测试、提交。

使用 `python scripts/compare_avilist.py --report <路径.json>` 可只读重建新旧概念ID、名称及中文显示名差异报告。当前结果见[完整差异](../research/avilist-2026-diff.json)。
