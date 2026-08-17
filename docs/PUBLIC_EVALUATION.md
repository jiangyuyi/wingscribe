# 公共评测方案

## 目标

WingScribe 的优化功能不应以用户拥有已整理、已标注的鸟类照片为前提。默认评测流程使用公共数据集，并允许在任意用户目录上执行无标签影子比较。

公共评测主要回答：

- 新代码是否造成可重复的识别回归。
- 裁切、质量评分和软先验在受控条件下是否改善结果。
- 新旧配置的运行时间、内存和显存成本有何变化。

公共评测不能单独回答“在某位用户自己的照片上提高了多少”。所有报告必须区分有标签准确率和无标签一致性指标。

## 数据集分工

### CUB-200-2011

首阶段公共回归集。它包含 200 类、11,788 张图片，以及每张图片的 bbox 和部位标注。

用途：

- 基础 Top-1、Top-5 回归。
- 对 bbox 注入平移和缩放扰动，测试裁切容错。
- 比较 single-crop 与 multi-crop。
- 施加合成退化，测试质量评分和识别稳定性。

限制：

- 主要是北美鸟类，不能代表中国物种分布。
- 图片通常比真实历史照片规整。
- 官方提示图片可能和 ImageNet/Flickr 预训练数据重叠。
- 图片仅限非商业研究和教育用途，仓库不得重新分发。

官方页面：https://www.vision.caltech.edu/datasets/cub_200_2011/

### iNaturalist 中国鸟类子集

第二阶段真实场景评估。使用公开元数据筛选鸟纲、中国坐标范围、有可靠物种标签和兼容许可的固定样本。

用途：

- 更接近用户拍摄条件的物种识别回归。
- 地理和月份软先验对候选排名的影响。
- 长尾类别和复杂背景下的行为变化。

限制：

- BioCLIP 训练包含 iNaturalist 2021，存在数据重叠风险。
- 类别和照片数量严重不均衡。
- IOC 与 iNaturalist 分类体系需要版本化映射。
- 每张图片许可独立，必须保存来源和许可元数据。

官方页面：https://www.inaturalist.org/pages/developers

### BIRD1445

BIRD1445 覆盖中国 1,445 种鸟类和多种模态，方向上最贴合 WingScribe。但在确认稳定下载入口、完整评估划分和使用许可前，不作为近期自动评测依赖。

论文页面：https://jeit.ac.cn/article/doi/10.11999/JEIT250647

## 报告规则

有标签评测至少输出：

- 样本数、有效样本数和失败样本数。
- Top-1、Top-5。
- 平均和分位数耗时。
- 数据集版本、manifest 哈希、模型和配置标识。

无标签影子评测至少输出：

- Top-1 一致率和 Top-5 重合率。
- 置信度、熵和候选排名变化。
- 分歧最大的样本清单。
- 平均耗时、CPU 内存和显存峰值。

报告不得把一致率称为准确率，也不得因公开集提升而直接宣称所有用户照片都会提升。

## 当前工具

官方数据：

- 页面：https://data.caltech.edu/records/65de6-vp158
- 文件：`CUB_200_2011.tgz`
- 官方 MD5：`97eceeb196236b17998738112f37df78`
- 建议解压位置：`data/evaluation/CUB_200_2011`，该目录已被 Git 忽略。

解压官方 CUB-200-2011 数据后，可以运行首版模型层基线：

```powershell
python scripts/evaluate_public.py `
  --dataset cub `
  --root D:\Datasets\CUB_200_2011 `
  --split test `
  --model bioclip-2 `
  --device auto `
  --batch-size 16 `
  --image-mode bbox `
  --output evaluation_results\cub-bioclip2.json
```

首次试运行可以添加 `--limit 20`。`--image-mode full` 评估整图，`bbox` 使用官方鸟体框和可配置 margin，`bbox-jitter` 进一步加入由 `--seed` 固定的框平移和缩放扰动。`multicrop-2` 使用 `1.0x/1.3x` 两路视野，`multicrop-3` 使用 `1.0x/1.3x/1.7x` 三路视野，并融合归一化 embedding。多路视野按 `--batch-size` 分块编码，避免视野数量成倍放大峰值显存。脚本不会下载或永久复制公共图片；裁切按批次生成并自动清理，报告目录默认被 Git 忽略。

当前工具使用 CUB 官方 bbox，而不是运行 WingScribe 的 YOLO 检测器，用来隔离识别器、裁切 margin 和框误差的影响。因此结果仍不代表 WingScribe 完整检测流水线的准确率。

两个模式运行完成后，可以生成差异报告：

```powershell
python scripts/compare_evaluation_reports.py `
  --baseline evaluation_results\cub-bbox.json `
  --candidate evaluation_results\cub-multicrop-2.json `
  --output evaluation_results\cub-comparison.json
```

有标签报告会统计 Top-1 改善和退化；无标签报告只统计 Top-1 一致率、Top-5 Jaccard、置信变化和分歧样本，不把一致率表述为准确率。

## 实施状态

已完成：

- CUB 官方目录和 train/test split 读取。
- 类别、图片路径、bbox 和 annotation 哈希校验。
- 官方 bbox 裁切、margin 和确定性框扰动。
- 两路/三路 multi-crop 批量编码与 embedding 加权融合。
- 批量评测、失败计数、Top-1、Top-5 和耗时分位数。
- 包含逐样本结果和运行元数据的 JSON 报告。
- 有标签改善/退化和无标签一致性的报告比较工具。
- 可重复的模糊、降采样、曝光和噪声退化质量回归报告。
- 不加载模型权重的单元测试和直接运行的命令行入口。

质量指标回归可以对任意公开图片目录运行：

```powershell
python scripts/evaluate_quality.py `
  --root D:\Datasets\CUB_200_2011\images `
  --limit 200 `
  --output evaluation_results\quality-degradation.json
```

报告分别保留每种退化的原始子指标和相对基线变化。`quality_decrease_rate` 只是指标方向检查，不代表识别准确率；噪声可能人为抬高梯度类锐度分数，这类反常结果应作为调整质量权重的依据，而不是隐藏或强制判定通过。

后续按独立提交推进：

1. 在公开集上运行 single-crop 与 multi-crop 对比矩阵并确定默认权重。
2. iNaturalist 中国鸟类固定 manifest 生成器和许可校验。
3. 任意本地目录上的无标签基线/实验影子比较。

截至 2026-08-17，已尝试从 CaltechDATA 官方地址下载，但当前连接速度约为 10KB/s，预计超过 24 小时，因此已停止。真实对比矩阵仍待取得完整压缩包并通过 MD5 校验后运行；当前单元测试使用合成的小型 CUB 目录，不应被表述为模型准确率实测。

## 仓库边界

- 不提交公共数据集图片、模型权重或私人照片。
- 不提交用户本地绝对路径。
- 可以提交数据适配器、manifest schema、少量虚构示例和匿名汇总。
- 下载器必须尊重来源许可、署名要求和限速，不通过网页抓取绕过官方数据渠道。
