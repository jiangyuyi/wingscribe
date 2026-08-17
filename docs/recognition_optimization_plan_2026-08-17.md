# WingScribe 鸟类识别优化计划（完整对话修订版）

## 1. 结论

完整对话涉及四类优化，它们的收益、风险和实施成本不同：

1. **地点标准化与地理/月度先验**：解决候选物种排序问题。
2. **多视野裁切与 embedding 融合**：解决单个 bbox 太紧或太松的问题。
3. **鸟体区域质量评分与连拍利用**：解决固定模糊阈值误删有效照片的问题。
4. **BioCLIP 2.5、视觉原型与 FAISS**：提升视觉特征本身，属于后续模型层优化。

结合当前代码，最高优先级不是立即引入 BioCLIP 2.5 或 FAISS，而是：

- 建立基于公共数据集的固定评估基线和可重复评估脚本，不要求用户先整理私有照片。
- 将当前“模糊即跳过”改为“记录质量并降低权重”。
- 将自由文本 `location_tag` 标准化为省、市、区县和地点。
- 在相同模型下验证单裁切、扩大裁切和多视野融合的真实收益。

这些改动完成后，才能判断模型替换和检索方案是否值得承担额外内存、速度、依赖和 installer 体积。

## 2. 当前代码与完整对话的对应关系

项目已经具备：

- YOLO 鸟体检测和单类别 bbox。
- `crop_padding` 控制的单路裁切。
- 裁切区域上的 Laplacian 模糊检测。
- BioCLIP / BioCLIP2 zero-shot 分类。
- 中国鸟类名单和国家级 `auto/china/global` 候选控制。
- 从多层目录提取日期、自由文本地点和源目录结构。
- 候选结果、人工修正结果和照片元数据的 SQLite 持久化。

当前主要问题：

- `QualityChecker` 只计算 Laplacian，并使用固定绝对阈值直接跳过照片。
- 每个检测框只产生一个裁切图；bbox 偏差会直接传递到识别结果。
- `LocalBirdRecognizer` 直接完成图片到分类结果，尚未提供稳定的 embedding 融合接口。
- `location_tag` 仍是自由文本，只能判断国家，不能支持省市/月度先验。
- 当前展示置信度是候选集合上的 softmax；不同候选数量、模型和先验下不可直接横向比较。
- 没有固定评估集，任何“感觉更准”都可能被样本差异误导。
- 人工确认过的历史照片尚未转化为本地视觉原型。

## 3. 目标架构

```text
原图 / EXIF / 目录路径
          |
          +--> PathParser ----------> 原始日期与地点文本
          |                              |
          |                              v
          |                       LocationResolver
          |                省 / 市 / 区县 / 地点 / 可信度
          |
          v
      BirdDetector
          |
          +--> detection bbox / detector score / bird pixel ratio
          |
          +--> ViewBuilder
          |      tight crop / medium crop / optional context crop
          |
          +--> QualityEvaluator
                 sharpness / contrast / exposure / size
                         |
                         v
                  Image Encoder
                         |
                   embedding fusion
                         |
               China closed-set visual Top-N
                         |
          +--------------+---------------+
          |                              |
          v                              v
  GeographicPriorProvider       Prototype / kNN（可选）
          |                              |
          +--------------+---------------+
                         v
                    ScoreReranker
                         |
                         v
      Top-K + 原始视觉分 + 重排分 + 质量与地点解释
```

每个模块必须可配置关闭。关闭新增模块后，结果应退回当前行为，便于对比和回滚。

## 4. 分阶段实施

### 阶段 0：公共评估基线与运行记录

默认评估流程不能要求每位用户先整理、标注自己的鸟类照片。首版采用“公共数据集回归 + 可选无标签影子评测”，私有人工评估集只作为高级用户后续提高结论可信度的可选项。

#### A. CUB-200-2011 裁切与质量回归集

- 使用官方类别、bbox 和部位标注，不在仓库中重新分发图片。
- 用于比较检测框 margin、单路/多路裁切和 embedding 融合。
- 对官方 bbox 注入可重复的平移、缩放和边界扰动，模拟检测框误差。
- 对图片施加可重复的模糊、降采样、曝光和噪声退化，检查质量指标和识别结果是否按预期变化。
- 该数据集以北美鸟类为主，照片分布较规整，只能验证算法回归，不能代表中国历史照片上的最终效果。
- 官方明确提示其图片可能与 ImageNet/Flickr 预训练数据重叠，因此不把绝对准确率作为模型泛化证明。

#### B. iNaturalist 中国鸟类子集

- 从带许可、物种、日期和坐标的公开记录中抽取 Aves、中国范围的固定子集。
- 通过保存观测 ID、照片 ID、标签、许可和数据版本生成可复现 manifest，不直接提交图片。
- 用于真实场景识别、长尾类别、月份和地理软先验的相对对比。
- BioCLIP 的训练数据包含 iNaturalist 2021，BioCLIP 2 的训练覆盖更广，因此必须记录潜在数据重叠；结果用于旧版/新版相对比较，不作为独立盲测成绩。
- 每张图片的许可可能不同，下载和缓存工具必须保留许可与作者信息，不允许绕过平台限速批量抓取。

#### C. 无标签影子评测

- 用户可选择任意照片目录并同时运行基线和实验配置，无需物种标签。
- 记录 Top-1 一致率、Top-5 重合率、置信度和熵变化、不同裁切间一致性、耗时、CPU 内存和显存峰值。
- 自动导出分歧最大的少量样本供人工查看，但不要求人工查看才能运行评测。
- 一致性不等于准确性；两个配置可能一致地给出错误答案，因此该部分只能发现行为变化和明显退化。

#### D. 地点解析合成回归集

地点解析不依赖照片。仓库保存由行政区划、别名和歧义规则生成的测试字符串，并覆盖父目录组合、旧称、简称、境外地点和 unknown。用户自己的历史目录字符串可作为本地扩展，但不是必需输入。

#### E. 可选私有抽查

若用户愿意提高结论可信度，可以只检查基线和实验配置分歧最大的 20 至 50 张照片，不需要预先建设 200 至 300 张正式评估集。绝对照片路径和私人数据不提交仓库；仓库只保存 schema、示例 manifest 和匿名汇总。

评估指标：

- Top-1、Top-5。
- 待确认率，以及待确认照片中的 Top-5 命中率。
- 单图耗时、每秒吞吐、CPU 内存和显存峰值。
- 按鸟体占比、清晰度、月份、地点和难种分组统计。

首个对比矩阵：

1. 当前发布版默认配置。
2. 禁用固定模糊跳过。
3. 单路 bbox + 不同 margin。
4. 两路和三路 multi-crop。
5. 地理/月度重排。
6. BioCLIP2 与 BioCLIP 2.5。

当前数据库不能直接提供可靠真值：它没有独立的人工确认来源字段，且现有数据量较小。数据库照片只能用于可选影子评测；后续新增 `label_source/manual_verified_at` 后，才能把明确确认的结果安全地积累为私有评估样本或视觉原型。

### 阶段 1：质量评分取代固定模糊跳过

当前逻辑在裁切图的 Laplacian 低于阈值时直接删除临时图并停止识别。完整对话指出，这对历史照片不够稳：轻微虚焦的大鸟可能仍可识别，而锐利背景也会干扰简单指标。

建议改为 `QualityEvaluator`：

- Laplacian variance：保留作为一个指标。
- Tenengrad：补充梯度能量。
- bird pixel ratio：检测框占原图比例。
- detector confidence：保存检测器分数。
- contrast / exposure clipping：检测过暗、过曝和极低对比。

首版不做复杂 AI 质量模型。输出统一的 `quality_score` 和原始子指标。

行为建议：

- 默认 `mode=weight`：继续识别，但在候选置信展示和连拍排序中体现质量。
- `mode=reject` 作为兼容选项，仅对极端不可用照片启用。
- 保留旧 `blur_threshold` 的迁移兼容，但不再推荐作为默认硬门槛。
- 不自动删除原图或识别证据。

### 阶段 2：地点标准化

新增独立 `LocationResolver`。`PathParser` 只负责提取原始路径元数据，行政区和地点语义不应继续堆入解析器。

匹配顺序：

1. EXIF GPS（接口先预留；存在时优先）。
2. 用户自定义地点别名和手动覆盖。
3. 城市、直辖市和省份精确匹配。
4. 区县、县级市反查所属城市。
5. 观鸟点词典匹配。
6. 未知地点报告和人工补充。
7. 高阈值模糊匹配放到后续版本，只提供候选提示。

关键规则：

- 合并有限层级的祖先目录，而不是只读照片直接父目录。
- 精确匹配优先，具体地点采用最长关键词匹配。
- “朝阳、长安、西湖、官厅”等歧义名称必须结合省份/父目录或人工别名。
- 不能可靠判断时返回未知，不应静默猜测。

建议文件：

- `config/dictionaries/china_admin_divisions.csv`：行政区划基础数据，记录来源和许可证。
- `config/dictionaries/location_aliases.yaml`：用户长期维护的观鸟点、旧称和覆盖规则。

统一输出：

```json
{
  "location_raw": "20240120_浙江临安天目山",
  "province": "浙江",
  "city": "杭州",
  "district": "临安",
  "site": "天目山",
  "source": "exact_site_alias",
  "confidence": 1.0
}
```

数据库保留 `location_tag`，新增标准地点字段，避免破坏旧库和现有页面。

缓存应以“规范化后的目录路径 + 词典版本”为 key；词典更新时可以自动失效，不建议只以文件夹名称作为永久缓存 key。

### 阶段 3：multi-crop 与 embedding 融合

不追求单个完美 bbox，而是让模型看到互补视野。

建议先比较两种配置：

```text
低成本两路：tight 1.0x + medium 1.3x
增强三路：tight 1.0x + medium 1.3x + context 1.7x
```

不建议首版默认加入整张原图：

- 历史照片可能存在多只鸟或多个物种。
- 整图背景可能压过目标鸟。
- 会增加一次完整 encoder 推理。

可以在“单检测目标且鸟体占比较高”时低权重加入 full frame，作为实验选项。

融合原则：

- 融合归一化 embedding，不平均已经 softmax 的百分比。
- medium crop 初始权重最高，因为它通常兼顾完整轮廓和细节。
- 所有视野在同一批次编码，降低 GPU 调用开销。
- CPU 模式允许退化为单路或两路，避免历史批处理耗时线性放大。

初始实验权重可设为：

```text
tight=0.25, medium=0.55, context=0.20
```

最终权重由阶段 0 评估集决定。

这一步需要把 `LocalBirdRecognizer` 拆成两个稳定接口：

- `encode_images(paths) -> normalized_embeddings`
- `classify_embedding(embedding, labels, top_k) -> candidates`

现有 `predict/predict_batch` 继续保留并基于新接口实现，避免破坏 API。

### 阶段 4：省市/月度软先验

地理先验必须重排而不是硬过滤。罕见鸟、迷鸟、迁徙期异常记录不能被行政区规则直接删除。

通用数据表：

```text
species_prior(
  scientific_name,
  region_level,
  region_code,
  month,
  observation_count,
  probability,
  source,
  source_version
)
```

回退链：

```text
site -> city -> province -> ecological region -> national
```

首版可只实现 city/province/national。

评分建议：

```text
final_logit = visual_logit
              + lambda_prior
              * location_confidence
              * clipped_log_prior
```

注意事项：

- 先暴露视觉 cosine/logit，不直接对当前展示百分比加权。
- 对 prior 修正值设置上下限，防止常见种完全压制高视觉相似度的少见种。
- 同时保存 visual Top-K 和 reranked Top-K，便于审计。
- 无地点、无月份或无先验数据时必须与纯视觉结果一致。

数据来源优先级：

1. 用户人工确认的历史照片，形成个人常见度统计。
2. 用户合法取得并导入的地区/月度观测汇总。
3. 核实许可证后再考虑公开平台或研究数据。

### 阶段 5：BioCLIP 2.5 可选模型

模型卡地址已在完整对话中给出：`imageomics/bioclip-2.5-vith14`。实施前仍需核对模型卡、OpenCLIP 兼容版本和许可证原文。

建议：

- 新增模型注册表，替代 `inference_local.py` 中不断扩展的硬编码 map。
- BioCLIP2 继续作为默认和回退模型。
- 第一目标硬件为 **RTX 5060 Laptop 8 GB**，分别测试 fp16、batch size、显存、吞吐和 installer 行为。
- RTX 4060 的历史结果只可作为参考，不能替代 RTX 5060 Laptop 上的实测。
- CPU 保持功能可用和稳定回退，不要求与 GPU 达到相同吞吐。
- **Radeon 780M 核显**列入下一阶段：需要单独评估 DirectML、ONNX Runtime、ROCm/Windows 支持现状和 OpenCLIP 算子兼容性，不与首轮 CUDA 实现耦合。
- 模型权重不直接打入 installer；按现有本地缓存/首次下载策略管理。
- 只有在固定评估集上收益显著且运行成本可接受时，才考虑修改默认值。

BioCLIP 2.5 的 ViT-H/14 规模更大，不能用公开 benchmark 代替目标机器上的实际测试。

### 阶段 6：人工确认照片的视觉原型

优先利用 WingScribe 已人工确认的照片，而不是立即导入授权复杂的外部图库：

1. 对人工确认的裁切图计算 embedding。
2. 按物种建立均值 prototype，或保留少量代表向量做 kNN。
3. 样本不足的物种继续使用 zero-shot。
4. 人工改标签后增量失效或重建相关物种原型。
5. 将 prototype 分数与 zero-shot 分数、地理先验分别记录后再融合。

首版使用 NumPy 余弦相似度即可。只有 embedding 数量达到数万至数十万且线性检索成为实际瓶颈时，再引入 FAISS，避免增加 Windows installer 复杂度。

### 阶段 7：连拍组和部位识别

连拍优化很有潜力，但自动融合前必须避免错误分组。

首版建议只做“连拍候选组 + 质量排序”：

- 同一目录。
- EXIF 时间间隔在可配置阈值内。
- 文件名序号连续作为辅助证据。
- 检测数量和 embedding 相似度用于防止把不同鸟混为一组。

先在 Web 中展示每组最优照片和质量排名，不自动删除低质量照片。验证分组可靠后，再实验质量加权 embedding 融合。

head crop 放在这一阶段之后：它对柳莺、鹀、鹟等难种可能有效，但自动定位鸟头的成本和误差明显高于整鸟 bbox。

暂不建议进入主流程：

- SAM 像素级抠图。
- 强降噪、强锐化、HDR。
- 生成式超分。
- 自动删除模糊照片。

这些操作可能移除或生成羽纹、翼斑、眼圈等关键分类特征。

## 5. 数据库与结果可解释性

建议保留现有字段，并增量增加：

- `location_raw`、`province`、`city`、`district`、`site`。
- `location_source`、`location_confidence`。
- `quality_score`，详细子指标可先存 JSON。
- `model_name`、`model_version`、`pipeline_version`。
- 重排前后的候选及各分数组成。

页面需要能回答：

- 地点从哪里匹配出来，命中了哪个关键词。
- 照片为何被判定为低质量。
- Top-1 是纯视觉第一，还是被地点/月度先验重排上来的。
- 使用了哪些裁切视野和模型版本。

## 6. 测试策略

每个独立 PR 都应先补测试：

- 地点：最长匹配、歧义名称、父目录约束、用户覆盖、未知地点、词典版本缓存。
- 质量：鸟体区域而非全图、指标归一化、权重模式、兼容 reject 模式。
- multi-crop：边界扩张、图像边缘裁切、批量顺序、embedding 归一化和单路回退。
- prior：地点层级回退、月份缺失、权重上限、无先验时结果不变。
- prototype：标签修改后的失效、样本不足回退、评估集隔离。
- installer：可选依赖、模型缺失、CPU/GPU 回退和 embedded runtime 自检。

## 7. 推荐 PR 顺序

1. 公共评估清单格式、CUB 适配器、通用评估脚本和基线报告。
2. `QualityEvaluator`，将固定模糊跳过改为可配置质量权重。
3. `LocationResolver`、行政区词典格式、用户 aliases 和预览 API。
4. 数据库标准地点字段及 pipeline 接入。
5. `encode_images/classify_embedding` 接口和两路 multi-crop。
6. 三路 multi-crop、质量元数据展示和性能调优。
7. `PriorProvider` 与省市/月度软重排。
8. BioCLIP 2.5 可选模型和目标硬件基准。
9. 人工确认照片的 prototype/kNN。
10. 连拍质量排序；根据实测再决定融合、head crop 和 FAISS。

## 8. 需要确认的产品选择

1. 地点首版覆盖中国大陆，还是同时覆盖港澳台和常见境外地点。
2. 是否接受数据库新增标准地点和质量字段，同时保留全部旧字段。
3. 是否同意精确/别名匹配自动采用，模糊匹配首版只提示不自动采用。
4. 当前硬模糊阈值是否改为默认不丢弃，仅标低质量；保留配置项允许用户恢复旧行为。
5. multi-crop 首版采用低成本两路，还是直接实现 tight/medium/context 三路。
6. BioCLIP 2.5 的第一目标设备为 RTX 5060 Laptop 8 GB；Radeon 780M 作为下一阶段独立后端计划。
7. 公共评估默认采用 CUB 回归集和 iNaturalist 中国鸟类固定子集，不要求用户准备私有评估集。
8. 地点解析、识别、质量和性能分别报告，避免把不同目标混成一个指标。
