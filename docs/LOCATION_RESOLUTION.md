# 地点标准化

`LocationResolver` 将 `PathParser` 提取的原始目录文本转换为结构化地点。当前模块是独立预览能力，尚未改变流水线候选鸟种、数据库字段或页面显示。

## 设计原则

- 用户别名优先于行政区词典。
- 具体地点采用最长匹配；歧义结果返回 `unknown`，不静默猜测。
- 别名可以用 `parent_matches` 约束父级目录文本。
- 原始 `location_tag` 始终保留，结构化结果是附加信息。
- 缺少词典或词典读取失败时安全返回未知。

## 行政区 CSV

格式参考 `config/dictionaries/china_admin_divisions.example.csv`：

```csv
province,city,district,aliases
浙江,杭州,临安,临安区|临安市
```

`aliases` 使用 `|` 或 `;` 分隔。示例文件不是完整行政区数据，不能直接作为生产词典。正式数据应记录来源、版本和许可证，并保存为独立的 `china_admin_divisions.csv`。

## 用户地点别名

格式参考 `config/dictionaries/location_aliases.example.yaml`：

```yaml
version: 1
aliases:
  - match: "天目山"
    province: "浙江"
    city: "杭州"
    district: "临安"
    site: "天目山"
```

对于“朝阳”等歧义名称，应使用更具体的 `match`，或增加 `parent_matches`：

```yaml
  - match: "朝阳公园"
    parent_matches: ["北京"]
    province: "北京"
    city: "北京"
    district: "朝阳"
    site: "朝阳公园"
```

解析结果包含 `location_raw`、`province`、`city`、`district`、`site`、`source` 和 `confidence`。后续预览接口验证可靠后，再考虑数据库字段和生产流水线接入。
