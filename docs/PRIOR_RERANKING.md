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
raw_adjustment = (log_prior - max_log_prior) * weight * location_confidence
final_logit = visual_logit + clamp(raw_adjustment, -max_adjustment, 0)
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

## iNaturalist 首轮验证

首轮数据使用 iNaturalist 官方 `observations/species_counts` 聚合接口生成：限定中国、鸟纲、物种级、research-grade 和观测日期不晚于 2021-12-31，按 12 个月分别聚合，并对评测清单中的 924 个候选物种做 Laplace 平滑。共聚合 6,707 个物种/月结果、54,193 条观测，其中 53,106 条匹配候选分类；生成文件 SHA-256 为 `11de580ba661ed7a84d052227840c6691b905466fb6281e898da6752b8bf1b4a`。先验文件为本地评测产物，不提交仓库或 installer。

冻结的 2022-2025 年 iNaturalist 中国鸟类子集共 450 张。预先固定 `weight=0.25`、`location_confidence=1.0`、`max_adjustment=1.0` 后，BioCLIP2 的 Top-1 从 66.67% 降至 65.56%，Top-5 从 86.44% 降至 86.22%；15 张改变 Top-1，其中 2 张改善、7 张退化，双侧精确配对检验 `p=0.1797`。

该配置没有收益，且全国月度观测频率容易把稀有种压向平台中的高频近似种，因此不接入生产，也不在同一测试子集上反复调权。后续只有在取得独立验证集，或建立许可与行政区映射均可追溯的更细粒度先验后，才重新评估。

月度维度到此停止，不作为后续生产设计方向。保留相关生成模式仅用于复现这次否决实验。

## 省级全年验证

省级目录使用 31 个 `CN-XX` 稳定代码。生成时逐项通过 iNaturalist Places API 校验官方地点的 `admin_level=10` 且祖先链包含中国 place `6903`；冻结样本通过官方观测 `place_ids` 映射，不读取或猜测 `place_guess`。省份 sidecar 绑定原 manifest SHA-256，错用清单时直接拒绝加载。

截至 2021-12-31 的省级全年聚合包含 6,787 个物种行、54,164 条观测，其中 53,077 条匹配 924 个候选物种；无截断。先验共 29,568 条记录，全部 `month=null`，由 31 个省级桶和 1 个全国回退桶组成。先验文件 SHA-256 为 `16e981d7462dc7676de79b2326a9a831e15fb4012def2990568e1154026dfd81`，省份 sidecar SHA-256 为 `77383fbe1abbd490c6f44c29e2860dd38a8385d9ce088d7bf67c6a8099bbec1b`；两者均为本地评测产物，不提交仓库或 installer。

同一 2022-2025 年 450 张冻结样本全部成功映射省份，覆盖 27 个省级区域。沿用唯一的预注册参数 `weight=0.25`、`location_confidence=1.0`、`max_adjustment=1.0` 后，BioCLIP2 Top-1 从 66.67% 提升到 67.11%，Top-5 从 86.44% 提升到 87.11%；20 张改变 Top-1，其中 7 张改善、5 张退化，双侧精确配对检验 `p=0.7744`。

结果方向为正但样本不足、效应很小且不显著。因此后续只保留“省级全年软先验”路线，不使用月度数据，也暂不接入生产。下一次权重或生产验证应使用独立数据，不能继续针对这 450 张测试样本调参。
