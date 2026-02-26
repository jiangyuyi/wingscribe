# 项目进度看板 (Progress Tracking)

## 📋 项目概览

- **项目名称**: WingScribe (飞羽志)
- **当前目标**: 移除Docker功能，修复物种显示，升级YOLO，数据库迁移
- **技术栈**: Python 3.10+ / FastAPI / YOLOv11 / BioCLIP (OpenCLIP) / MySQL / ExifTool

## ✅ 已实现功能 (Status: Stable)

- [X] **核心架构**: 模块化设计，分离核心处理、识别引擎、数据管理、Web 界面
- [X] **YOLOv8 鸟类检测**: `src/core/detector.py` - 自动 CUDA→CPU 降级
- [X] **BioCLIP 物种识别**: `src/recognition/inference_local.py` - 本地离线识别
- [X] **多 API 支持**: 支持 local/dongniao/huggingface 多种识别模式
- [X] **SQLite 数据库**: `src/metadata/ioc_manager.py` - IOC 鸟类分类数据管理
- [X] **EXIF 元数据写入**: `src/metadata/exif_writer.py` - 支持 IPTC/XMP/UserComment
- [X] **Web 管理界面**: `src/web/app.py` - FastAPI + WebSocket 实时日志
- [X] **文件路径解析**: `src/core/io/path_parser.py` - 从文件夹结构提取日期/位置
- [X] **路径生成器**: `src/core/io/path_generator.py` - 基于模板生成输出路径
- [X] **路径安全抽象**: `src/core/io/fs_manager.py` - allowed_roots 权限控制
- [X] **图像处理**: `src/core/processor.py` - 裁剪/缩放/质量检测
- [X] **配置管理**: `src/utils/config_loader.py` - YAML 配置加载与缓存
- [X] **智能扫描**: `SmartScanner` - 日期范围剪枝优化
- [X] **批处理引擎**: `ThreadPoolExecutor` + 缓冲区管理
- [X] **错误恢复机制**: 模型重载、自动降级、日志记录

## 🛠 正在进行中 (Active Tasks)

### 1. 移除 Docker 相关功能 [已完成]
**状态**: ✅ 完成

- [X] 删除 Dockerfile.cpu
- [X] 删除 Dockerfile.gpu
- [X] 删除 docker-compose.yml
- [X] 删除 docker-compose.remote.yml
- [X] 更新 scripts/deploy.sh 移除Docker命令
- [X] 清理 nul 文件

---

### 2. 修复物种列表分类显示问题 [已完成]
**状态**: ✅ 完成

- [X] CUDA 稳定性检查（重试 + synchronize）
- [X] 模型延迟加载机制
- [X] Excel 中文编码修复（XML 解析）
- [X] 修复重置后中文名丢失问题（传递 refs_dir 参数）
- [X] 提交: `59a2213`

---

### 3. 修复 deploy.ps1 路径问题 [已完成]
**状态**: ✅ 完成

- [X] 将 deploy.ps1 从 scripts/ 移到项目根目录
- [X] 将 deploy.sh 从 scripts/ 移到项目根目录
- [X] 修复 setup_tui.py 中的旧指引（scripts/deploy.ps1 → ./deploy.ps1）
- [X] 提交: `48e9ff5`

---

### 4. GPU 库未正确安装到 venv [已完成]
**状态**: ✅ 完成

**问题原因**: requirements.txt 中只写了 `torch`，pip 默认安装 CPU 版本

**修复方案**:
- [X] 修改 deploy.ps1，在安装依赖前检测 CUDA 版本
- [X] 根据 CUDA 12.x/11.x 安装对应版本的 PyTorch
- [X] 从 PyTorch 官方源安装（download.pytorch.org）
- [X] 提交: `3a01a8d`

---

### 5. PyTorch 不支持 RTX 50 系列 (sm_120) [已完成]
**状态**: ✅ 完成

**错误**:
```
NVIDIA GeForce RTX 5060 Laptop GPU with CUDA capability sm_120 is not compatible
with the current PyTorch installation.
The current PyTorch install supports CUDA capabilities sm_50 sm_60 sm_61 sm_70 sm_75 sm_80 sm_86 sm_90.
```

**分析**:
- RTX 50 系列是 2025 年发布的新显卡 (sm_120/Blackwell架构)
- PyTorch 稳定版最高支持 sm_90
- **关键发现**: 需要使用 **CUDA 12.8 (cu128)** 版本的 nightly，而不是 cu121/cu124

**修复方案**:
- [X] 自动检测 RTX 50 系列 GPU
- [X] 使用 nightly 版本代替稳定版
- [X] **nightly 从 cu124 改为 cu128 (CUDA 12.8)**
- [X] 完全卸载旧版本后再安装
- [X] 添加 pip cache purge
- [X] 验证通过

---

### 6. 启用模糊检测逻辑 [已完成]
**状态**: ✅ 完成

**问题**: 配置文件中 `blur_threshold` 和 `confidence_threshold` 未被实际使用

**调研结果**:
- `src/core/quality.py` 中存在 Laplacian 方差法模糊检测逻辑，但未被 pipeline 调用
- 该方法适合检测鸟类照片的对焦模糊（阈值建议80-100）

**修改文件**:
- [X] `src/pipeline_runner.py` - 在裁剪成功后添加 QualityChecker 调用
- [X] 低于模糊度阈值的图片会被自动跳过并删除临时文件
- [X] `blur_threshold` 配置现在生效（默认40.0，可在settings.yaml中调整）

---

### 7. 升级 YOLO 检测模型 [已完成]
**状态**: ✅ 完成

**调研结果**:
- YOLO26 (2025.9发布) vs YOLOv11 vs YOLOv8 对比
- YOLO26n: mAP 40.9, 2.4M参数, 5.4B FLOPs (最优轻量化)
- YOLOv11n: mAP 39.5, 2.6M参数, 6.5B FLOPs
- YOLOv8n: mAP 37.3, 3.2M参数, 8.7B FLOPs (最成熟稳定)

**推荐**: 升级到 YOLO26（精度最高、参数量最小、推理最快）

**AMD CPU 支持分析**:
- PyTorch 在 Windows 上对 AMD GPU 支持有限（需要 ROCm，仅支持 Linux）
- AMD 锐龙 CPU 可以运行 PyTorch CPU 版本（无 GPU 加速）
- 当前代码已支持 CUDA→CPU 自动降级，AMD CPU 用户会使用 CPU 推理
- **无需额外修改**，现有设备选择逻辑已兼容

**修改文件**:
1. `config/settings.yaml` - 更新 yolo_model 从 `yolov8n.pt` 改为 `yolo26n.pt`
2. `src/core/detector.py` - 更新注释和文档字符串
3. `tests/test_core.py` - 更新测试中的模型名称
4. `tests/test_detector.py` - 新增单元测试（13个测试用例，全部通过）

**单元测试结果**:
- 13个测试用例全部通过
- 覆盖: CUDA稳定性检查、设备选择、模型加载、检测功能、错误处理

---

### 8. 切换数据库到 MySQL [待开始]
**目标**: 从 SQLite 迁移到 MySQL，支持远程访问

**推荐**: MySQL 或 PostgreSQL

**修改文件**:
- `src/metadata/ioc_manager.py` - 修改数据库连接逻辑
- `config/settings.yaml` - 添加数据库配置项

---

### 9. 创建精简版 Docker (仅浏览) [待开始]
**目标**: 创建仅包含 Web 浏览功能的轻量级 Docker

**功能范围**:
- 照片浏览
- 分类筛选
- 物种搜索

---

### 10. 修复裁切图片路径重复和前端显示问题 [已完成]
**状态**: ✅ 完成

**问题**:
- 输出路径出现 `clip/clip` 重复
- 前端无法正常显示裁切后的图片

**原因分析**:
- 源文件在 `Y:/1按年份/2026/clip/20260110北京小漕村附近/` 目录下
- `source_structure` 计算为 `clip/20260110北京小漕村附近`
- 与 `output.root_dir = "Y:/1按年份/2026/clip"` 组合后导致路径重复

**修复方案**:
- [X] 修改 `path_generator.py`：添加 `_normalize_source_structure()` 方法，自动去除与 output_root 重复的前缀
- [X] 修复 `app.py` 中绝对路径处理逻辑
- [X] 更新 deploy.ps1 配置提示，说明 output 路径设置规则
- [X] 提交: `cb3aab0`

---

### 11. Batch Processing 日志显示问题 [已完成]
**状态**: ✅ 完成

**问题**:
- Web UI的Batch Processing界面不显示后台日志

**修复方案**:
- [X] 前端添加WebSocket连接状态日志和错误处理
- [X] 后端添加TaskManager详细日志记录
- [X] 提交: `482b466`

---

### 12. 首页翻页按钮消失问题 [已完成]
**状态**: ✅ 完成

**问题**:
- 在没有筛选任何物种的首页，翻页按钮消失了

**原因分析**:
- 首页 `status-bar` div 中只渲染了文本信息，没有静态渲染分页按钮
- 后端已传递 `has_next`, `has_prev`, `next_offset`, `prev_offset` 变量，但模板未使用
- JavaScript 的 `updatePhotoGrid` 只在点击分类树筛选时才调用，首页加载时不触发

**修复方案**:
- [X] 在 index.html 模板中添加静态分页按钮
- [X] 使用 Jinja2 变量渲染 Previous/Next 链接
- [X] 仅在有筛选条件时显示"清除筛选"按钮

---

### 13. 排除裁切输出目录 [已完成]
**状态**: ✅ 完成

**问题**:
- 扫描源目录时，会把裁切输出目录（如 `clip/`）也包含进来
- 导致已裁切的照片会被再次处理，浪费资源
- 临时文件目录硬编码为 data/processed/temp，导致产生不必要的目录

**修复方案**:
- [X] 在 SmartScanner 中添加 exclude_dirs 参数
- [X] 使用预解析的绝对路径 self.output_root 进行排除
- [X] 修复临时文件目录，使用配置的 output.root_dir
- [X] 两种扫描模式（SmartScanner 和 list_dir）都已处理
- [X] 支持 UNC 网络路径格式的路径转换

**修改文件**:
- `src/pipeline_runner.py`: SmartScanner 添加 exclude_dirs 参数，使用 self.output_root

---

### 15. 完善 Linux 部署脚本 deploy.sh [已完成]
**目标**: 将 deploy.sh 完善为与 deploy.ps1 功能一致

**差异分析**:
- `deploy.sh` 已具备完整功能，但缺少 `deploy.ps1` 中的 PyTorch GPU 检测逻辑
- 需要添加：RTX 50 系列 GPU 检测和 nightly PyTorch 安装支持

**修改计划**:
1. 分析 deploy.ps1 中的 PyTorch 安装逻辑
2. 在 deploy.sh 中添加相同的功能:
   - GPU 型号检测（RTX 50 系列识别）
   - CUDA 12.8 (cu128) nightly 版本安装
   - 完全卸载旧版本后再安装
   - pip cache purge
3. 在 Linux/WSL 环境测试

**已完成修改**:
- [X] 在 `install_python_deps()` 中添加 GPU 检测逻辑
- [X] 添加 RTX 50 系列检测（使用正则匹配）
- [X] 添加 CUDA 12.8 nightly 版本安装支持
- [X] 添加完全卸载旧版本 PyTorch
- [X] 添加 pip cache purge
- [X] 添加单独的 `pytorch` 命令（重新安装 PyTorch）
- [X] 更新配置生成中的 yolo_model 从 yolov8n.pt 改为 yolo26n.pt

---

### 14. 数据库存储相对路径 [已完成]
**状态**: ✅ 完成

**目标**: 数据库只存储相对路径，绝对路径从配置文件的 base_dir 为起点计算

**修改计划**:
1. `config/settings.yaml` - 新增 base_dir 配置
2. `src/metadata/ioc_manager.py` - 添加相对路径转换逻辑
   - 写入时: 绝对路径 → 相对路径
   - 读取时: 相对路径 → 绝对路径
3. `src/web/app.py` - 使用新的转换函数

**简化点**:
- 无需迁移现有数据（可重置数据库）
- 只在入库/出库两处转换

**注意**:
- 重置数据库后生效

---

### 16. 完善 Linux 部署脚本 deploy.sh (续) [已完成]
**状态**: ✅ 完成

**新增功能**:
- [X] 修复 ExifTool 包名（perl-image-exiftool → libimage-exiftool-perl）
- [X] 修复 pip 路径检测（添加 pip3 检测）
- [X] 添加自动 sudo 功能（install_git, install_python, install_exiftool, install_venv_if_needed）
- [X] 自动检测系统 Python 版本（优先使用 python3）

---

### 17. 修复 signal only works in main thread 问题 [已完成]
**状态**: ✅ 完成

**问题**: Linux 服务器上运行 pipeline 时报错:
```
signal only works in main thread of the main interpreter
```

**原因**:
- `signal.SIGALRM` 只能在主线程中使用
- 检测器在 ThreadPoolExecutor 工作线程中首次被加载

**修复方案**:
- [X] 添加线程检测: `threading.current_thread() == threading.main_thread()`

---

### 18. 修复多线程同时下载 YOLO 模型问题 [已完成]
**状态**: ✅ 完成

**问题**: 4 个线程同时启动，同时下载 YOLO 模型

**修复方案**:
- [X] 添加 `_detector_lock` 线程锁
- [X] 使用 double-check locking 模式

---

### 19. 添加 HuggingFace 镜像配置 [已解决]
**状态**: ✅ 已解决

**问题**: 国内服务器下载 BioCLIP 模型超时

**根本原因**:
- `open_clip` 库在模块加载时就执行了 `import open_clip`
- 此时 `HF_ENDPOINT`/`HF_HUB_URL` 环境变量尚未设置
- huggingface_hub 内部已缓存了默认 URL，导致后续设置的环境变量无效

**解决方案**:
1. **修改 `src/recognition/inference_local.py`**:
   - 将 `import open_clip` 改为 lazy import（延迟导入）
   - 添加 `_get_open_clip()` 函数，在设置环境变量后才导入 open_clip
   - 这样确保 huggingface_hub 使用镜像 URL

2. **修改 `src/recognition/cloud/factory.py`**:
   - Web API 调用 `LocalBirdRecognizer` 时没有传递 `hf_mirror` 参数
   - 添加从配置中读取 `hf_mirror` 并传递给识别器的代码

**关键代码**:
```python
# inference_local.py - lazy import
_open_clip = None
def _get_open_clip():
    global _open_clip
    if _open_clip is None:
        import open_clip as _oc
        _open_clip = _oc
    return _open_clip

# 在 __init__ 中先设置环境变量，然后才调用 _get_open_clip()
if hf_mirror:
    os.environ['HF_ENDPOINT'] = hf_mirror
    os.environ['HF_HUB_URL'] = hf_mirror
# 然后 lazy load open_clip
```

**验证**: 手动测试确认镜像生效
