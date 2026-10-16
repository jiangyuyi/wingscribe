# IOC 名录与中文分类

物种和目科属名称由 `src/metadata/ioc_manager.py` 管理，导入入口为 `scripts/import_ioc_data.py`。

## 准备数据

在 `config/settings.yaml` 的 `paths` 下明确设置：

```yaml
paths:
  db_path: "data/db/wingscribe.db"
  references_path: "data/references"
  ioc_list_path: "data/references/Multiling IOC 15.1_d.xlsx"
```

这是配置片段，需合并进已有 `paths`，不要替换整个配置。导入脚本直接读取 `paths.db_path`，即使应用有回退路径，也不能在导入时省略该字段。

参考目录中的可选 CSV：

| 文件 | 用途 |
| --- | --- |
| `bird_order_mapping.csv` | 目拉丁名到中文名 |
| `bird_family_mapping.csv` | 科拉丁名到中文名 |
| `bird_genus_mapping.csv` | 属拉丁名到中文名 |

CSV 有表头，第一列为匹配键，第二列为中文值。还可设置 `paths.cn_taxonomy_path` 提供中文分类 Excel；属映射合并时 CSV 优先。

## 导入

先备份已有数据库，再在仓库根目录执行：

```powershell
python scripts/import_ioc_data.py
```

脚本加载存在的映射后导入 IOC Excel，并输出少量校验记录和物种数量。缺失映射时可能保留拉丁名称；数量取决于实际数据版本，旧记录中的 10,750 条不作为当前验收标准。

原 `SOLUTION_Chinese_Taxonomy.md` 提到的 `update_ioc_with_chinese_taxonomy.py` 不在仓库中，已从操作指南移除。更新名录时应记录来源、版本和使用条件，不能仅根据旧修复记录推定数据准确性。
