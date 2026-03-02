# WingScribe 配置指南

本文档详细介绍了 WingScribe 的各项配置选项。系统主要使用 `config/` 目录下的两个 YAML 文件进行配置：

1.  `settings.yaml`: 主配置文件，包含路径、处理逻辑和应用行为设置。
2.  `secrets.yaml`: 安全配置文件，用于存储 API 密钥（此文件不会被 Git 追踪）。

---

## 1. 主配置 (`settings.yaml`)

### A. 路径配置 (`paths`)

控制 WingScribe 从哪里读取图片以及将结果保存到何处。所有路径都以 `base_dir` 为基准。

| 参数 | 描述 | 默认值 / 示例 |
| :--- | :--- | :--- |
| `base_dir` | **基准目录**。驱动器根目录，所有源文件、输出文件和数据库都以此为基准进行相对路径存储。例如 `Y:/`，源文件在 `Y:/1按年份/2026`，输出在 `Y:/输出/2026`。 | `Y:/` |
| `references_path` | 参考数据目录，用于存放 IOC 鸟类分类数据等（相对于 base_dir）。 | `data/references` |
| `sources` | 定义需要扫描图片的源目录列表（相对于 base_dir）。 | 见下文 |
| `db_path` | SQLite 数据库文件路径（相对于 base_dir）。 | `data/db/wingscribe.db` |
| `ioc_list_path` | IOC 世界鸟类名录 Excel 文件路径（相对于 base_dir）。 | `data/references/Multiling IOC 15.1_d.xlsx` |
| `model_cache_dir` | 模型缓存目录，存放下载的 YOLO、BioCLIP 等模型文件（相对于 base_dir）。 | `data/models` |

#### 源目录定义 (`sources`)
`sources` 列表中的每一项可以包含以下属性：
*   `path`: 文件夹路径，相对于 `base_dir` 的路径（如 `1按年份/2026`）。
*   `recursive`: `true` 表示递归扫描子文件夹。
*   `enabled`: `true` 表示启用此源。
*   `structure_pattern` (可选): 用于从文件夹结构中提取元数据（日期、地点）的正则表达式。
    *   *默认*: 使用内部逻辑猜测 `YYYYMMDD_地点` 格式。
    *   *自定义*: 使用命名组 `(?P<date>...)` 和 `(?P<location>...)`。

```yaml
sources:
  - path: "1按年份/2026"
    recursive: true
    enabled: true
    # 示例：匹配 "2024-01-27 [奥森公园]" 这样的文件夹
    structure_pattern: "(?P<date>\\d{4}-\\d{2}-\\d{2}) \\\\[(?P<location>.*)\\]"
```

#### 输出配置 (`paths.output`)

| 参数 | 描述 |
| :--- | :--- |
| `root_dir` | 处理后图片的保存目录，相对于 `base_dir`（如 `输出/2026`）。 |
| `write_back_to_source` | `true`: 将 EXIF 数据直接写回**源文件**。`false` (默认): 仅修改复制到 `root_dir` 的文件。 |
| `structure_template` | 定义处理后图片的文件夹结构和文件名格式。 |

**模板变量:**
*   `{date}`, `{year}`, `{month}`, `{day}`: 从文件夹名或 EXIF 获取的日期。
*   `{location}`: 从文件夹名获取的地点。
*   `{species_cn}`: 鸟种中文名 (例如 "麻雀")。
*   `{species_sci}`: 拉丁学名 (例如 "Passer montanus")。
*   `{confidence}`: 识别置信度 (0-100)。
*   `{filename}`: 原始文件名。
*   `{source_structure}`: 保留源目录的相对层级结构。

---

### B. 处理设置 (`processing`)

控制计算机视觉流水线的参数。

| 参数 | 描述 | 默认值 |
| :--- | :--- | :--- |
| `device` | 硬件加速。选项: `cuda` (NVIDIA GPU), `cpu`, `auto` (自动检测)。 | `auto` |
| `yolo_model` | YOLO 检测模型文件名。推荐使用 `yolo26n.pt`（精度最高、推理最快）。 | `yolo26n.pt` |
| `confidence_threshold` | **检测**鸟类目标的最低置信度 (0-1)。 | `0.5` |
| `blur_threshold` | 拉普拉斯方差阈值。低于此分数的图片会被标记为模糊并跳过。推荐值 40-100。 | `40.0` |
| `target_size` | 识别前裁切图的缩放尺寸 (像素)。 | `640` |
| `crop_padding` | 在检测到的鸟类方框周围额外保留的像素。 | `200` |

---

### C. 识别设置 (`recognition`)

配置用于识别物种的 AI 引擎。

| 参数 | 描述 | 选项 |
| :--- | :--- | :--- |
| `mode` | 使用的识别引擎。 | `local` (BioCLIP 本地), `api` (HuggingFace API), `dongniao` (懂鸟 API) |
| `region_filter` | 候选词过滤器。`auto` 会根据文件夹名关键词自动切换。 | `null` (全球), `china` (仅中国分布), `auto` |
| `top_k` | 保存的备选物种数量。 | `5` |
| `alternatives_threshold` | 如果首选结果置信度高于此值 (0-100)，Web 界面将不显示备选建议（认为非常可信）。 | `70` |
| `low_confidence_threshold` | 低于此分数的匹配将被标记为"不确定"。 | `60` |
| `hf_mirror` | HuggingFace 镜像加速地址。国内服务器使用 `https://hf-mirror.com`，国外留空。 | `""` |

#### 引擎特定配置

**本地模型 (BioCLIP):**
```yaml
local:
  model_type: "bioclip-2"     # 推荐使用 "bioclip-2" 以获得更高精度
  batch_size: 512             # 文本编码批次大小 (通常不需要修改)
  inference_batch_size: 16    # 图片推理批次大小，如果显存不足(低于 8G)请调小
```

---

### D. Web 服务设置 (`web`)

| 参数 | 描述 | 默认值 |
| :--- | :--- | :--- |
| `host` | Web 服务器监听地址。`0.0.0.0` 表示监听所有网络接口。 | `0.0.0.0` |
| `port` | Web 服务器端口。 | `8000` |
| `log_level` | 日志等级。`info` 仅显示摘要信息，`debug` 显示每张图片的处理详情。 | `info` |

---

## 2. 密钥配置 (`secrets.yaml`)

此文件保存您的 API 密钥。默认情况下不存在此文件，您需要手动创建。

### 结构

```yaml
# HuggingFace API (仅当 recognition.mode 为 'api' 时需要)
hf_api_key: "hf_..."

# 懂鸟 API (仅当 recognition.mode 为 'dongniao' 时需要)
dongniao_api_key: "your_key..."
```

---

## 3. 环境变量

您也可以使用环境变量覆盖部分设置（适用于 Docker/云环境）：

*   `WS_PORT`: Web 服务器端口 (默认: 8000)
*   `WS_HOST`: Web 服务器主机 (默认: 0.0.0.0)

---

## 4. 配置示例

### Windows 示例
```yaml
paths:
  base_dir: "Y:/"
  sources:
    - path: "1按年份/2026"
      recursive: true
      enabled: true
  output:
    root_dir: "输出/2026"
    structure_template: "{source_structure}/{filename}_{species_cn}_{confidence}"
    write_back_to_source: false
  db_path: "data/db/wingscribe.db"
  ioc_list_path: "data/references/Multiling IOC 15.1_d.xlsx"
  model_cache_dir: "data/models"

processing:
  device: "auto"
  yolo_model: "yolo26n.pt"
  confidence_threshold: 0.5
  blur_threshold: 40.0
  target_size: 640
  crop_padding: 200

recognition:
  mode: "local"
  region_filter: "auto"
  top_k: 5
  alternatives_threshold: 70
  low_confidence_threshold: 60
  hf_mirror: "https://hf-mirror.com"
  local:
    model_type: "bioclip-2"
    batch_size: 512
    inference_batch_size: 16

web:
  host: "0.0.0.0"
  port: 8000
  log_level: "info"  # 日志等级: debug(详细) / info(简洁)
```

### Linux 示例
```yaml
paths:
  base_dir: "/mnt/picturessd"
  sources:
    - path: "1按年份/2026"
      recursive: true
      enabled: true
  output:
    root_dir: "输出/2026"
    structure_template: "{source_structure}/{filename}_{species_cn}_{confidence}"
    write_back_to_source: false
  db_path: "data/db/wingscribe.db"
  ioc_list_path: "data/references/Multiling IOC 15.1_d.xlsx"
  model_cache_dir: "data/models"

processing:
  device: "auto"
  yolo_model: "yolo26n.pt"
  confidence_threshold: 0.5
  blur_threshold: 40.0
  target_size: 640
  crop_padding: 200

recognition:
  mode: "local"
  region_filter: "auto"
  top_k: 5
  alternatives_threshold: 70
  low_confidence_threshold: 60
  hf_mirror: "https://hf-mirror.com"
  local:
    model_type: "bioclip-2"
    batch_size: 512
    inference_batch_size: 16

web:
  host: "0.0.0.0"
  port: 8000
```
