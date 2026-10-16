# WingScribe 配置指南

核对日期：2026-10-16。以下以代码实际读取为准；表中数值是配置示例，不保证所有缺省回退相同。系统主要使用 `config/` 目录下的两个 YAML 文件进行配置：

1.  `settings.yaml`: 主配置文件，包含路径、处理逻辑和应用行为设置。
2.  `secrets.yaml`: 安全配置文件，用于存储 API 密钥（此文件不会被 Git 追踪）。

---

## 1. 主配置 (`settings.yaml`)

### A. 路径配置 (`paths`)

控制 WingScribe 从哪里读取图片以及将结果保存到何处。

**路径约定**：所有命令在项目根目录运行：
- `sources.path` 和 `output.root_dir` 使用**绝对路径**
- 其他相对路径（`references_path`, `ioc_list_path`, `model_cache_dir`）相对于**项目根目录**（包含 `src/` 与 `config/` 的目录）
- 移除了 `base_dir` 配置项

| 参数 | 描述 | 默认值 / 示例 |
| :--- | :--- | :--- |
| `sources` | 定义需要扫描图片的源目录（**必填，绝对路径**）。 | 见下文 |
| `output.root_dir` | 处理后图片的保存目录（**必填，绝对路径**）。 | `D:/Photos/Birds/Output` |
| `references_path` | 参考数据目录（相对于项目根目录）。 | `data/references` |
| `db_path` | SQLite 数据库文件路径（相对于项目根目录）。 | `data/db/wingscribe.db` |
| `ioc_list_path` | IOC 世界鸟类名录 Excel 文件路径（相对于项目根目录）。 | `data/references/Multiling IOC 15.1_d.xlsx` |
| `model_cache_dir` | 模型缓存目录，存放下载的 YOLO、BioCLIP 等模型文件（相对于项目根目录）。 | `data/models` |

#### 源目录定义 (`sources`)
`sources` 列表中的每一项可以包含以下属性：
*   `path`: 文件夹路径，**必须使用绝对路径**（如 `D:/Photos/Birds/2026`）。
*   `recursive`: `true` 表示递归扫描子文件夹。
*   `enabled`: `true` 表示启用此源。
*   `structure_pattern` (可选): 用于从文件夹结构中提取元数据（日期、地点）的正则表达式。
    *   *默认*: 使用内部逻辑猜测 `YYYYMMDD_地点` 格式。
    *   *自定义*: 使用命名组 `(?P<date>...)` 和 `(?P<location>...)`。

以下片段应放在 `paths` 下：

```yaml
paths:
  sources:
    - path: "D:/Photos/Birds/2026"
      recursive: true
      enabled: true
```

自定义正则的日期输出须与路径解析逻辑匹配，先用测试目录验证。

#### 输出配置 (`paths.output`)

| 参数 | 描述 |
| :--- | :--- |
| `root_dir` | 处理后图片的保存目录（**必填，绝对路径**，如 `D:/Photos/Birds/Output`）。 |
| `write_back_to_source` | `true`: 将 EXIF 数据直接写回**源文件**。`false` (默认): 自动流水线不写原图。人工校对当前仍会写原图，详见 [项目状态](../development/status.md)。 |
| `structure_template` | 定义处理后图片的文件夹结构和文件名格式。 |

**模板变量:**
*   `{date}`, `{year}`, `{month}`, `{day}`: 路径解析元数据中的日期；不要据此假定已经采集秒级 EXIF 时间。
*   `{location}`: 从文件夹名获取的地点。
*   `{species_cn}`: 鸟种中文名 (例如 "麻雀")。
*   `{species_sci}`: 拉丁学名 (例如 "Passer montanus")。
*   `{confidence}`: 置信度字符串，例如 `85pct`。
*   `{filename}`: 原始文件名的主干，不含扩展名。
*   `{source_structure}`: 保留源目录的相对层级结构。

---

### B. 处理设置 (`processing`)

控制计算机视觉流水线的参数。

| 参数 | 描述 | 默认值 |
| :--- | :--- | :--- |
| `device` | 硬件加速。选项: `cuda` (NVIDIA GPU), `cpu`, `auto` (自动检测)。 | `auto` |
| `yolo_model` | YOLO 检测模型路径，不作跨模型性能保证。 | `data/models/yolo26n.pt` |
| `confidence_threshold` | **检测**鸟类目标的最低置信度 (0-1)。 | `0.5` |
| `blur_threshold` | 拉普拉斯方差阈值。仅在 `legacy_reject` 下用于跳过模糊图片；小于等于 0 时该模式不计算质量。 | `40.0` |
| `quality_mode` | 质量处理模式。`legacy_reject` 保持原有模糊过滤；`score_only` 只计算质量指标而不跳过；`disabled` 关闭质量计算。 | `legacy_reject` |
| `target_size` | 识别前裁切图的缩放尺寸 (像素)。 | `640` |
| `crop_padding` | 在检测到的鸟类方框周围额外保留的像素。 | `200` |

在启用质量计算的 `legacy_reject`（阈值大于 0）和 `score_only` 模式下，新处理照片会把综合质量分及完整子指标保存到数据库，便于后续审计；`disabled` 及升级前的历史照片保持空值。当前质量分不会参与物种排序，也不会额外删除照片。

---

### C. 识别设置 (`recognition`)

配置用于识别物种的 AI 引擎。

| 参数 | 描述 | 选项 |
| :--- | :--- | :--- |
| `mode` | 使用的识别引擎。 | `local` (BioCLIP 本地), `api` (旧式 API 客户端，需配置 URL/key), `dongniao` (懂鸟 API) |
| `region_filter` | 候选词过滤器。`auto` 会根据文件夹名关键词自动切换。 | `null` (全球), `china` (仅中国分布), `auto` |
| `top_k` | 保存的备选物种数量。 | `5` |
| `alternatives_threshold` | 如果首选结果置信度高于此值 (0-100)，Web 界面将不显示备选建议（认为非常可信）。 | `70` |
| `low_confidence_threshold` | 低于此分数的匹配将被标记为"不确定"。 | `60` |
| `hf_mirror` | HuggingFace 镜像加速地址。国内服务器使用 `https://hf-mirror.com`，国外留空。 | `""` |

#### 引擎特定配置

**本地模型 (BioCLIP):**
```yaml
recognition:
  local:
    # 2.5 保持实验选项；显式指定模型，避免缺省回退差异
    model_type: "bioclip-2"
    inference_batch_size: 16
```

支持的本地模型为 `bioclip`、`bioclip-2` 和实验性的 `bioclip-2.5-vith14`。未知名称会直接报错。请显式设置 `recognition.local.model_type`：样例使用 `bioclip-2`，但流水线缺少该项时回退 `bioclip`。样例中的 `local.batch_size` 暂未接入读取，文本编码批次在代码中固定为 512。

进一步代码核查发现：`local.inference_batch_size` 虽被读取，当前流水线没有使用它切分批次。因此不能承诺调小此值可降低显存；示例保留该配置，但其实现缺口见 [项目状态](../development/status.md)。

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

### 流水线密钥结构

```yaml
recognition:
  api:
    key: "填写服务密钥"
    url: "填写与旧式 API 客户端协议匹配的服务 URL"
  dongniao:
    key: "填写懂鸟密钥"
    url: "填写实际懂鸟服务 URL"
```

根据所选模式只填写所需部分。旧 secrets 样例中的顶层 `hf_api_key` 和 `dongniao_api_key` 不供流水线实际读取。统一 REST 云适配器使用 `cloud.*` 结构，见 [识别 API](../reference/recognition-api.md)。

## 3. 启动参数

Web 入口支持 `python src/web/app.py --host 127.0.0.1 --port 8000`，命令行参数优先于 `web.host/port`。当前代码没有读取 `WS_HOST` / `WS_PORT`，不再将其列为可用覆盖方式。

---

## 4. 配置示例

### Windows 示例
```yaml
paths:
  # 照片源目录（必填，绝对路径）
  sources:
    - path: "D:/Photos/Birds/2026"
      recursive: true
      enabled: true

  # 输出目录（必填，绝对路径）
  output:
    root_dir: "D:/Photos/Birds/Output"
    structure_template: "{source_structure}/{filename}_{species_cn}_{confidence}"
    write_back_to_source: false

  # 以下路径相对于项目根目录
  references_path: data/references
  db_path: data/db/wingscribe.db
  ioc_list_path: data/references/Multiling IOC 15.1_d.xlsx
  model_cache_dir: data/models

processing:
  device: "auto"
  yolo_model: "yolo26n.pt"
  confidence_threshold: 0.5
  blur_threshold: 40.0
  quality_mode: "legacy_reject"
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
    inference_batch_size: 16

web:
  host: "0.0.0.0"
  port: 8000
  log_level: "info"
```

### Linux 示例
```yaml
paths:
  # 照片源目录（必填，绝对路径）
  sources:
    - path: "/mnt/pictures/Birds/2026"
      recursive: true
      enabled: true

  # 输出目录（必填，绝对路径）
  output:
    root_dir: "/mnt/pictures/Birds/Output"
    structure_template: "{source_structure}/{filename}_{species_cn}_{confidence}"
    write_back_to_source: false

  # 以下路径相对于项目根目录
  references_path: data/references
  db_path: data/db/wingscribe.db
  ioc_list_path: data/references/Multiling IOC 15.1_d.xlsx
  model_cache_dir: data/models

processing:
  device: "auto"
  yolo_model: "yolo26n.pt"
  confidence_threshold: 0.5
  blur_threshold: 40.0
  quality_mode: "legacy_reject"
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
    inference_batch_size: 16

web:
  host: "0.0.0.0"
  port: 8000
```

---

## 5. Web 配置页面

 WingScribe 提供了 Web 配置界面，您可以通过以下方式访问：

- 地址：`http://localhost:8000`（如果端口为 8000）
- 进入「设置」页面可以修改配置

**配置页面映射**：

| Web 页面字段 | 配置文件项 |
| :--- | :--- |
| 照片基准目录 | `paths.sources[0].path` |
| 输出目录 | `paths.output.root_dir` |
