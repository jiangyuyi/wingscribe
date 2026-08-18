# 物种软先验重排

## 当前边界

软先验基础层目前是独立模块，不读取 `settings.yaml`，不接入 Web 或生产 pipeline，也不会改变默认识别结果。它只为后续离线评测提供可审计接口。

本地识别器通过 `score_embeddings()` 暴露所有候选物种的 pre-softmax `100 × cosine` 视觉 logits。先验必须在完整候选集上加入 logits，不能只重排视觉 Top-K，也不能直接修改当前展示百分比。

## 文件格式

```json
{
  "schema_version": 1,
  "source": {
    "name": "example",
    "version": "2026-08-18"
  },
  "records": [
    {
      "scientific_name": "Passer montanus",
      "region_level": "province",
      "region_code": "CN-11",
      "month": 5,
      "probability": 0.12
    }
  ]
}
```

`region_level` 只允许 `site`、`city`、`province`、`national`；`month=null` 表示全年。记录键必须唯一，概率必须在 `(0, 1]`，来源和版本应能追溯到生成数据。

## 回退与评分

查找顺序为：

```text
site 当月 -> site 全年
city 当月 -> city 全年
province 当月 -> province 全年
national 当月 -> national 全年
```

各候选概率转为 log-prior，并相对当前候选中的最大值计算非正调整：

```text
final_logit = visual_logit + clamp(log_prior - max_log_prior, -max_adjustment, 0)
                              * weight
                              * location_confidence
```

最终调整有硬上限。没有任何匹配、权重为零、地点置信度为零或上限为零时，调整向量全为零，结果与纯视觉排序一致。

每个输出候选保留：

- `visual_logit`
- `prior_adjustment`
- `final_logit`
- softmax `confidence`
- 命中的区域层级、区域代码、月份和原始概率

## 数据风险

- iNaturalist 观测可生成低成本全国/月度先验，但观测数量同时受人口、可达性、季节活动和平台用户偏好影响，不等同于真实物种丰度。
- 用同一批观测同时生成先验和评测会造成泄漏。若采用 iNaturalist，建议只用 2021 年及以前观测生成先验，并只在 2022 年以后固定样本上评测。
- 省市级先验必须先建立坐标到稳定行政区代码的版本化映射；不能根据自由文本 `place_guess` 静默猜测。
- 任何公共来源都必须记录许可、查询条件、时间截点和聚合方式。原始私人路径和逐图结果不得提交。

当前没有真实先验文件进入仓库或 installer，也没有生产默认权重。真实数据验证通过前，这一功能保持评测专用。
