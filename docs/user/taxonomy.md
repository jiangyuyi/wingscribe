# AviList 名录与中文显示名

本分支使用 **AviList v2025b** 作为新的物种候选名录，共 11,131 种。来源为 [AviList 官方发布](https://www.avilist.org/checklist/v2025b/)，许可 CC BY 4.0；完整引用、来源文件 SHA-256、转换说明和中文名来源见 `data/references/avilist-v2025b.json`。只导入 species 层级，不把属或亚种作为识别候选。

`data/references/avilist-v2025b.csv` 是随项目分发的固定版本名录。新空库由流水线或系统重置入口初始化；已有非空库不会在启动时被静默替换，需要执行显式迁移。

```yaml
paths:
  db_path: "data/db/wingscribe.db"
  taxonomy_catalogue_path: "data/references/avilist-v2025b.csv"
```

未设置 `taxonomy_catalogue_path` 时使用项目内上述默认文件。旧 `ioc_list_path` 不再控制新候选集，但保留旧 IOC 文件作为名称来源与研究材料。禁止用旧 IOC 导入覆盖已经版本化的 AviList 库。

## 中文名与历史标签

官方 v2025b 表没有中文名或直接 IOC 对照列。10,983 种沿用 IOC 15.1 中相同学名的中文显示名；148 种以学名显示。目科属中文显示名来自仓库现有映射 CSV。它们均不是 AviList 官方中文译名，映射文件中缺少中文时显示拉丁名。

**同学名不等于分类范围相同。** `taxonomy_provenance` 记录 Avibase 标识、版本和中文显示名来源；`taxonomy_legacy_review` 将旧名称列为 `same_name_unverified` 或 `unmatched`，均不代表已完成分类概念对应。不猜测拆分、合并或更名后的旧照片归属。

本次采用低成本保留方式：旧名录完整留在 `taxonomy_legacy`，旧照片的标签和人工确认信息不变，`photos.taxonomy_version` 标为 `legacy-unversioned`。后续重新识别新增记录，或人工重新选择物种，才记录当前名录版本。旧照片仍可能按同学名出现在新分类树中，但这种显示关联不是已核实的历史分类迁移。

旧中国鸟种白名单也不能直接视为 AviList 的地域筛选表。活动库为 AviList 时，未声明匹配版本的 `china`/`auto` 白名单会回退到完整候选集并记录警告，避免漏掉改名或拆分后的物种；首次文本编码会更慢。待重新核实地域名单后，才设置 `paths.china_list_taxonomy_version: AviList-v2025b` 启用过滤，不能只加版本标签而不核对内容。

## 迁移与回退

关闭正在使用该数据库的应用和流水线后，在锁定环境中执行。数据库必须放在本机；照片可在 NAS。

```powershell
# 只读预览
python scripts/migrate_avilist.py --database data/db/wingscribe.db --report data/backups/avilist-preview.json

# 应用：先备份，再在事务中替换活动名录，保留全部照片标签
python scripts/migrate_avilist.py --database data/db/wingscribe.db --apply --backup-dir data/backups --report data/backups/avilist-migration.json
```

报告记录版本、物种数量、保留照片数、备份路径及旧名称复核清单。相同版本再次执行不会重复导入；不同版本需要单独迁移方案。发布文件校验不符会拒绝加载，不能手动编辑 CSV 后继续使用旧 manifest。

`pre_schema_backup` 是结构调整前的完整数据库备份；`backup_path` 是活动名录替换前的事务一致性备份。恢复时先关闭应用，保留当前数据库副本，再将报告中的 `pre_schema_backup` 复制回原数据库路径。备份包含照片索引，建议另行保存到可靠位置；Git 不包含 `data/backups/`。照片文件没有被迁移命令修改。

## 重新生成发布文件

下载 manifest 中固定的官方 XLSX，使用相同 IOC 中文名工作簿和目科属映射，调用 `scripts/migrate_avilist.py --build-from <官方文件> --ioc-names <IOC中文文件> ...`。源文件哈希不符会拒绝构建；此选项只重新生成名录，是否改库仍由 `--apply` 决定。生成文件和 manifest 必须一起审核、测试、提交。
