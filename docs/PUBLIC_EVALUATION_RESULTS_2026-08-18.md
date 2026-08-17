# 公共评测结果（2026-08-18）

## 评测范围

- 数据集：CUB-200-2011 官方 test split，5,794 张、200 类。
- 数据完整性：镜像下载的原始 `CUB_200_2011.tgz` 与 [CaltechDATA 官方记录](https://data.caltech.edu/records/65de6-vp158)的 MD5 `97eceeb196236b17998738112f37df78` 一致。
- 图像输入：官方 bird bbox，margin 0.15；未运行 WingScribe YOLO 检测器。
- 候选集：CUB 官方 200 个英文类别名。
- 精度：CUDA fp16；BioCLIP2 batch 16，BioCLIP 2.5 batch 1。
- 硬件：NVIDIA GeForce RTX 5060 Laptop GPU，8 GB；PyTorch 2.10.0+cu128。

## 完整结果

| 模型 | Top-1 | Top-5 | 平均耗时/张 | 峰值 allocated | 峰值 reserved |
| --- | ---: | ---: | ---: | ---: | ---: |
| BioCLIP2 ViT-L/14 | 88.61% | 97.38% | 26.6 ms | 1,188 MB | 2,224 MB |
| BioCLIP 2.5 ViT-H/14 | 90.65% | 97.98% | 39.8 ms | 2,376 MB | 4,558 MB |

BioCLIP 2.5 相对 BioCLIP2：

- Top-1 提升 2.04 个百分点，Top-5 提升 0.60 个百分点。
- 229 张由错误变正确，111 张由正确变错误，净改善 118 张。
- Top-1 预测发生变化 435 张，两模型 Top-1 一致率 92.49%。
- 配对正确性变化的双侧精确二项检验 `p=1.46e-10`。
- 平均推理耗时增加约 50%，峰值 allocated/reserved 显存约为 BioCLIP2 的 2.0/2.05 倍。

## Multi-Crop 初步结果

固定 seed 的 200 类分层样本上，两路 multi-crop（bbox margin 0.0/0.35，embedding 权重 0.35/0.65）未优于单 bbox：

| 模型 | 单 bbox Top-1/Top-5 | 两路 Top-1/Top-5 |
| --- | ---: | ---: |
| BioCLIP2 | 88.0% / 99.0% | 88.0% / 98.5% |
| BioCLIP 2.5 | 89.5% / 98.5% | 89.0% / 98.0% |

当前两路视野和权重不进入生产默认流程。若继续实验，应先重新设计 crop margin 和融合权重，再在固定分层样本上筛选，避免直接消耗完整测试集。

## 结论与边界

BioCLIP 2.5 在这套完整公共测试上具有明确的 Top-1/Top-5 收益，且可在目标 RTX 5060 Laptop 8 GB 上稳定运行，适合作为可选高精度模型继续评估。它仍不替换生产默认 BioCLIP2：CUB 主要覆盖北美鸟种，[官方页面](https://www.vision.caltech.edu/datasets/cub_200_2011/)还提示图片可能与 ImageNet 或 Flickr 预训练数据重叠，因此该结果不能直接外推为中国鸟类、用户原图或完整检测流水线上的同等收益。

模型权重、公共图片和含本地绝对路径的逐样本 JSON 报告均不提交仓库；本文件只保存匿名汇总。
