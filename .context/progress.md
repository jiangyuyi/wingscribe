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

---

### 20. Linux 下原图切换无效 [已完成]
**状态**: ✅ 完成

**问题**: Windows 下点击裁切图可以正常切换显示原图，但 Linux 下点击无效

**配置信息 (Linux)**:
```yaml
paths:
  base_dir: "/mnt/picturessd/1按年份/2026"
  allowed_roots:
    - "/mnt/picturessd/1按年份/2026"
  sources:
    - path: "."  # 相对于 base_dir
      recursive: true
      enabled: true
  output:
    root_dir: "clip"  # 相对于 base_dir
```

**分析**:
1. 前端代码 (`index.html:970-977`): 使用 `mousedown`/`mouseup` 事件切换图片
2. 后端 `resolve_web_path()` 将 `original_path` 转换为 `/static/roots/{idx}/...` URL
3. 如果路径解析失败，返回 `None`，前端 `rawSrc` 为空，事件监听器直接 return

**已添加调试日志**:
- 在 `resolve_web_path()` 添加详细日志
- 记录输入路径、绝对路径、allowed_roots 匹配情况

**待确认**:
- 需要在 Linux 服务器上查看日志输出
- 确认数据库中 `original_path` 的存储格式
- 确认 `allowed_roots` 的实际值

---

### 21. Pipeline 执行页面增加按文件和文件夹执行功能 [已完成]
**状态**: ✅ 完成

**目标**: 在 Pipeline 执行页面增加按文件和文件夹选择执行的功能

**需求**:
- 读取文件夹列表并支持多选
- 用户可以选择特定文件或文件夹进行单独处理

**需求确认** (2026-02-28):
1. **界面**: 新增独立的执行选择界面（树形多选）
2. **数据来源**: 从配置的 sources 路径扫描文件夹结构
3. **处理方式**: 选中文件夹后递归处理所有子文件夹
4. **执行逻辑**: 只处理选中的文件/文件夹，忽略日期范围筛选器
5. **去重**: 自动跳过库中已存在的文件

**性能优化 - 批量哈希查询**:
- 问题: 现有 `check_hash_exists()` 逐个文件查询数据库，10000文件需10000次SQL
- 优化: 添加 `get_all_hashes()` 批量查询接口，一次获取所有哈希到内存
- 适用: 适合10万级以下文件库

**实现计划**:

#### 阶段 1: 后端 - 数据库优化
- [X] `src/metadata/ioc_manager.py` - 添加 `get_all_hashes()` 方法

#### 阶段 2: 后端 - Pipeline 扩展
- [X] `src/pipeline_runner.py` - 添加 `existing_hashes` 参数支持
- [X] `src/pipeline_runner.py` - 添加 `run_by_folders(paths, recursive)` 方法

#### 阶段 3: 后端 - 新增 API
- [X] `src/web/app.py` - 添加 `/api/pipeline/folders` 获取文件夹树
- [X] `src/web/app.py` - 添加 `/api/pipeline/start_by_folders` 执行API
- [X] `src/web/app.py` - TaskManager 支持路径列表模式

#### 阶段 4: 前端 - 新增选择界面
- [X] `src/web/templates/admin.html` - 添加 Tab 切换（日期范围/文件夹）
- [X] 添加文件夹树形选择组件
- [X] 添加 JavaScript API 调用

**提交**: `4e74213`

---

### 21.1 修复文件夹路径和UI问题 [已完成]
**状态**: ✅ 完成

**修复内容**:
- [X] 问题1: 修改 `_build_folder_tree()` 添加 `base_rel_path` 参数，返回正确的相对路径
- [X] 问题2: 添加 `IGNORED_DIRS` 集合，排除回收站文件夹
- [X] 问题3: 添加 CSS 样式修复 Tab 按钮高亮颜色

**提交**: `60baad9`

---

### 21.2 修复 Pipeline 执行后UI状态和刷新问题 [已完成]
**状态**: ✅ 完成

**修复内容**:
- [X] 问题1: 修改日志检测，匹配 "Pipeline completed" 和 "Pipeline (by folders) completed"
- [X] 问题1: 添加错误检测，匹配 "Error:" 和 "Pipeline failed"
- [X] 问题2: 添加 loadStats() 刷新统计数据，新增 /api/stats API
- [X] 问题3: 删除未实现的 storage usage 显示

**提交**: `475101b`

---

### 21.3 修复 Pipeline UI展示问题 [已完成]
**状态**: ✅ 完成

**修复内容**:
- [X] 问题1: 改为追加日志而非清空，保留历史日志
- [X] 问题2: 文件夹模式不显示箭头
- [X] 问题3: history表格文件夹路径分行显示

**提交**: `9f0669d`

---

### 21.4 修复 Pipeline 路径生成问题 [已完成]
**状态**: ✅ 完成

**问题1: 裁切图片路径丢失中间目录**
- 问题1&3: 修改 run_by_folders 使用正确的 source_root
- 问题2: 随问题1一起修复（未再复现）

**提交**: `37346a0`

---

#### 阶段 3: 后端 - 新增 API
- [ ] `src/web/app.py` - 添加 `/api/pipeline/folders` 获取文件夹树
- [ ] `src/web/app.py` - 添加 `/api/pipeline/start_by_folders` 执行API
- [ ] `src/web/app.py` - TaskManager 支持路径列表模式

#### 阶段 4: 前端 - 新增选择界面
- [ ] `src/web/templates/index.html` - 添加 Tab 切换（日期范围/文件文件夹）
- [ ] 添加文件夹树形选择组件
- [ ] 添加 JavaScript API 调用

**涉及文件**:
- `src/metadata/ioc_manager.py`
- `src/pipeline_runner.py`
- `src/web/app.py`
- `src/web/templates/index.html`

---

### 22. 照片切换功能改用按钮切换 [已完成]
**状态**: ✅ 完成

**目标**: 将点击切换改为两个按钮切换

**需求**:
- 不再使用长按/鼠标按下切换
- 添加两个按钮：「显示裁切图」「显示原图」
- 用户点击按钮切换显示

**修改内容**:
- [X] 在照片卡片左上角添加"裁切"和"原图"两个切换按钮
- [X] 点击按钮即可切换显示裁切图或原图
- [X] 移除原来的长按提示交互方式
- [X] 按钮根据是否有裁切图/原图自动启用/禁用
- [X] 提交: `adc318d`

---

### 23. 新增鸟种统计页面 [待开始]
**目标**: 新增一个页面显示拍到过的鸟种统计信息

**需求**:
- 显示鸟种总数
- 显示鸟种列表（类似当前侧边栏的展示方式）
- 不显示照片数量
- 支持点击后跳转到该鸟种的筛选页面

---

### 24. 增强一键部署脚本 [已完成]
**状态**: ✅ 完成

**修改内容**:
- [X] deploy.ps1 添加后台启动 (-Daemon/-d)、停止 (-Stop/-s)、状态 (-Status/-t) 功能
- [X] deploy.sh 添加后台启动 (-d)、停止 (-s)、状态 (-t) 功能
- [X] 两边都支持端口 (-p/--port) 和绑定地址 (-b/--bind) 参数
- [X] 添加 PID 文件管理 (.wingscribe.pid)
- [X] 更新菜单选项，增加后台管理入口
**目标**: 为 deploy.ps1 和 deploy.sh 添加后台启动和后台停止功能

**需求**:
1. **后台启动功能**:
   - 使用 `-Daemon` 或 `-d` 参数启动服务
   - 服务在后台运行，不阻塞终端
   - 支持指定端口（默认 8000）
   - 支持指定绑定地址（默认 0.0.0.0）
   - 启动成功后输出服务 URL 和 PID

2. **后台停止功能**:
   - 使用 `-Stop` 或 `-s` 参数停止服务
   - 通过 PID 文件查找并终止进程
   - 支持强制终止（-Force）
   - 停止前尝试优雅关闭，等待进程结束

3. **PID 文件管理**:
   - 在项目根目录创建 `.wingscribe.pid` 文件
   - 记录进程 PID 和启动时间
   - 启动时检查是否已有进程在运行

4. **状态查询功能**:
   - 使用 `-Status` 或 `-t` 参数查看服务状态
   - 显示是否在运行、PID、启动时间、端口

**修改文件**:
- `deploy.ps1` (Windows PowerShell)
- `deploy.sh` (Linux/macOS bash)

**实现方案**:

#### deploy.ps1 (PowerShell)
```powershell
# 新增参数
param(
    [switch]$Daemon,
    [switch]$Stop,
    [switch]$Status,
    [switch]$Force,
    [int]$Port = 8000,
    [string]$Bind = "0.0.0.0"
)

# PID 文件路径
$PID_FILE = ".wingscribe.pid"

# 启动函数
function Start-WingScribeDaemon {
    # 检查端口是否占用
    $proc = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "端口 $Port 已被占用" -ForegroundColor Red
        exit 1
    }

    # 后台启动
    $process = Start-Process -FilePath "python" `
        -ArgumentList "src/web/app.py", "--port", $Port, "--host", $Bind `
        -PassThru -NoNewWindow

    # 保存 PID
    @{
        pid = $process.Id
        port = $Port
        time = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    } | ConvertTo-Json | Out-File $PID_FILE

    Write-Host "服务已启动: http://$Bind`:$Port (PID: $($process.Id))" -ForegroundColor Green
}

# 停止函数
function Stop-WingScribeDaemon {
    if (-not (Test-Path $PID_FILE)) {
        Write-Host "服务未运行（无 PID 文件）" -ForegroundColor Yellow
        return
    }

    $info = Get-Content $PID_FILE | ConvertFrom-Json
    $pid = $info.pid

    if (-not (Get-Process -Id $pid -ErrorAction SilentlyContinue)) {
        Write-Host "进程不存在，可能已手动停止" -ForegroundColor Yellow
        Remove-Item $PID_FILE -Force
        return
    }

    Stop-Process -Id $pid -Force:$Force
    Remove-Item $PID_FILE -Force
    Write-Host "服务已停止" -ForegroundColor Green
}

# 状态函数
function Get-WingScribeStatus {
    if (-not (Test-Path $PID_FILE)) {
        Write-Host "服务未运行" -ForegroundColor Yellow
        return
    }

    $info = Get-Content $PID_FILE | ConvertFrom-Json
    $proc = Get-Process -Id $info.pid -ErrorAction SilentlyContinue

    if ($proc) {
        Write-Host "服务运行中" -ForegroundColor Green
        Write-Host "  PID: $($info.pid)"
        Write-Host "  端口: $($info.port)"
        Write-Host "  启动时间: $($info.time)"
    } else {
        Write-Host "服务已停止（PID 文件存在但进程不存在）" -ForegroundColor Yellow
        Remove-Item $PID_FILE -Force
    }
}
```

#### deploy.sh (Bash)
```bash
# PID 文件路径
PID_FILE=".wingscribe.pid"

# 启动函数
start_daemon() {
    # 检查端口
    if lsof -i:$PORT >/dev/null 2>&1; then
        echo "端口 $PORT 已被占用"
        exit 1
    fi

    # 后台启动
    nohup python3 src/web/app.py --port $PORT --host $BIND > /dev/null 2>&1 &
    PID=$!

    # 保存 PID
    echo "{\"pid\":$PID,\"port\":$PORT,\"time\":\"$(date '+%Y-%m-%d %H:%M:%S')\"}" > $PID_FILE

    echo "服务已启动: http://$BIND:$PORT (PID: $PID)"
}

# 停止函数
stop_daemon() {
    if [[ ! -f $PID_FILE ]]; then
        echo "服务未运行（无 PID 文件）"
        return
    fi

    PID=$(grep -o '"pid":[0-9]*' $PID_FILE | grep -o '[0-9]*')

    if ! ps -p $PID > /dev/null 2>&1; then
        echo "进程不存在，可能已手动停止"
        rm -f $PID_FILE
        return
    fi

    kill $PID 2>/dev/null
    rm -f $PID_FILE
    echo "服务已停止"
}

# 状态函数
status_daemon() {
    if [[ ! -f $PID_FILE ]]; then
        echo "服务未运行"
        return
    fi

    PID=$(grep -o '"pid":[0-9]*' $PID_FILE | grep -o '[0-9]*')

    if ps -p $PID > /dev/null 2>&1; then
        echo "服务运行中 (PID: $PID)"
    else
        echo "服务已停止（PID 文件存在但进程不存在）"
        rm -f $PID_FILE
    fi
}
```

---

### 26. SQLite 数据库本地存储与定期备份 [已完成]
**目标**: 将 SQLite 数据库文件放在本地目录（而非 NAS），并实现定期备份

**背景**:
- 当前数据库文件存储在 NAS 上（base_dir 目录下）
- SQLite 不适合网络存储（性能差、锁问题）
- 需要将 db_path 独立于 base_dir 配置

**实现**:
1. **db_path 独立配置**:
   - 不设置时，默认相对于运行目录 (`data/db/wingscribe.db`)
   - 支持绝对路径（如 `C:/Users/jiang/data/wingscribe.db`）
   - 支持相对路径（相对于运行目录）

2. **备份脚本**:
   - 使用 SQLite `.backup` 命令确保安全
   - 支持自定义源目录和目标目录
   - 自动清理 7 天前的旧备份

**修改文件**:
- [X] `src/web/app.py` - db_path 路径解析逻辑
- [X] `src/pipeline_runner.py` - db_path 路径解析逻辑
- [X] `config/settings.yaml` - 添加注释说明
- [X] `config/settings.example.yaml` - 更新示例
- [X] `scripts/backup_db.ps1` - Windows 备份脚本
- [X] `scripts/backup_db.sh` - Linux/macOS 备份脚本

**使用方法**:
```bash
# Windows
.\scripts\backup_db.ps1 -Source "data\db\wingscribe.db" -Destination "Y:\备份\wingscribe"

# Linux
./scripts/backup_db.sh "data/db/wingscribe.db" "/mnt/nas/backup/wingscribe" 7
```

---

### 27. 地点信息包含多余年份前缀 [已完成]
**状态**: ✅ 完成

**问题**:
- 目前生成的地点信息格式为 `2025_北京柳荫公园`
- 正确格式应该是 `北京柳荫公园`（去掉年份前缀）

**分析**:
- 当文件夹结构是 `年份/地点`（如 `2025/北京柳荫公园`）时
- path_parser 会把年份目录 `2025` 也当作地点的一部分

**修复方案**:
- 在 `path_parser.py` 中添加跳过纯数字文件夹的逻辑
- 4位及以上纯数字的文件夹会被识别为年份目录并跳过
- 8位日期格式仍然会被正确识别为日期

**修改文件**:
- [X] `src/core/io/path_parser.py` - 添加跳过纯数字年份目录的逻辑
- [X] `tests/test_path_parser.py` - 添加测试用例验证修复

**测试结果**:
- 11 个测试用例全部通过

---

### 28. CorrectID 后保存路径错误 [已完成]
**状态**: ✅ 完成

**问题**:
- 在 Web 界面修正物种 ID 后（Correct ID）
- 裁切图的保存路径与原来不一致
- 错误地保存到了当前代码运行目录下，而不是与原来的裁切图路径一致

**原因分析**:
- 在 `update_label` 函数中，`PathGenerator` 初始化时直接使用了配置的 `output.root_dir`
- 没有像其他地方那样基于 `base_dir` 解析相对路径
- 导致生成的路径是相对于当前工作目录，而非配置的 base_dir

**修复方案**:
- 修改 `src/web/app.py` 第 976-985 行
- 添加 `is_absolute_path` 检查，解析相对路径时加上 `base_dir` 前缀
- 与其他地方（如第 225-232 行）保持一致

**修改文件**:
- [X] `src/web/app.py` - 修复 output_root 路径解析

**测试结果**:
- 76 个测试用例全部通过

---

### 29. 配置文件路径统一基准重构 [已完成]
**目标**: 简化路径配置，统一使用绝对路径，解决路径混乱问题，便于图形化配置

**需求**:
1. 移除 `base_dir` 配置项
2. `references_path` 相对于安装路径（即相对于项目根目录）
3. `sources` 的 `path` 使用绝对路径
4. `output.root_dir` 使用绝对路径
5. 其他缓存路径（`ioc_list_path`, `model_cache_dir`）均相对于安装路径
6. 同步修改 example、readme 和 configuration.md 的说明
7. Web 配置页面改为：
   - 照片基准目录 → 对应 `sources[0].path`
   - 输出目录 → 对应 `output.root_dir`

**修改文件**:
- `config/settings.yaml` - 移除 base_dir，调整配置格式
- `config/settings.example.yaml` - 更新示例
- `src/utils/config_loader.py` - 移除 base_dir 相关逻辑
- `src/web/app.py` - 修改路径解析逻辑，修改配置页面映射
- `src/pipeline_runner.py` - 移除 base_dir 依赖
- `src/core/io/fs_manager.py` - 简化路径验证逻辑
- `src/core/io/local.py` - 简化路径验证逻辑
- `docs/CONFIGURATION.md` - 更新文档说明
- `README.md` - 更新配置说明

**当前配置 vs 重构后配置**:

| 配置项 | 当前 | 重构后 |
|--------|------|--------|
| base_dir | D:/Data/WingScribe/ | **移除** |
| sources.path | `1按年份/` (相对) | **必填绝对路径**，如 `D:/照片/2026` |
| output.root_dir | `''` (相对) | **必填绝对路径**，如 `D:/输出/2026` |
| references_path | 相对于 base_dir | **相对项目根目录**，如 `data/references` |
| ioc_list_path | 相对于 base_dir | **相对项目根目录** |
| model_cache_dir | 相对于 base_dir | **相对项目根目录** |
| db_path | 相对运行目录 | 保持不变 |

**相对路径基准统一为"项目根目录"**:
- start_web.bat 运行时会切换到项目根目录
- 所有相对路径都以此为基准
- 包括：references_path, ioc_list_path, model_cache_dir, db_path

**优点**:
1. 所有路径配置都使用绝对路径，清晰直观
2. 照片基准目录和输出目录直接在配置页面设置对应的 sources.path 和 output.root_dir
3. 避免相对路径在不同工作目录下解析出不同结果的问题
4. 统一相对路径的基准为项目根目录

**用户确认**:
1. ✅ sources 只需要1个路径
2. ✅ output.root_dir 设为必填项
3. ✅ 不需要迁移数据库（重置后生效）
4. ✅ 相对路径基准统一为项目根目录

**待开始**: ✅

---

### 30. 配置页面读取/写入配置错误 [已完成]
**状态**: ✅ 完成

**问题描述**:
- 配置页面上照片基准目录无法正常显示
- 设置目录会写入到错误的配置位置

**问题原因**:
1. **读取问题**: `get_nested_value()` 函数使用字符串索引访问数组
   - `sources[0].path` 被拆分为 `['sources', '0', 'path']`
   - 第二次循环时 `value['0']` 用字符串 `'0'` 访问数组，但数组应该用数字 `0` 访问
   - 导致 `sources[0].path` 的值无法正确读取，返回 `undefined`

2. **Fallback 问题**: `get_default_definition()` 使用了旧的 `base_dir` 字段
   - 应该使用 `sources[0].path`

**修复方案**:
1. 修复 `src/web/templates/settings.html` 中的 `get_nested_value()` 函数
   - 将数组索引字符串转换为数字再访问
2. 更新 `get_default_definition()` 函数使用正确的字段名
3. 修复后端 `app.py` 中的 `set_nested_value()` 函数，支持数组索引

**修改文件**:
- [X] `src/web/templates/settings.html` - 修复 get_nested_value 和 get_default_definition
- [X] `src/web/app.py` - 修复 set_nested_value 支持数组索引

---

### 31. 配置保存后重启功能无效 [已完成]
**状态**: ✅ 完成

**问题描述**:
- 配置页面的"保存后重启服务"勾选框不起作用
- 保存配置后只是刷新了前端页面，没有真正重启后端服务

**修复方案**:
1. 后端添加真正的重启功能：
   - 保存启动参数（host, port, python 路径）
   - restart_server API 启动新的服务进程
   - 使用后台线程延迟退出旧进程
2. 前端修改保存逻辑：
   - 保存配置后调用 /api/config/restart 接口
   - 等待服务重启后刷新页面

**修改文件**:
- [X] `src/web/app.py` - 添加启动参数变量，修改 restart_server 实现真正的重启
- [X] `src/web/templates/settings保存逻辑调用重启.html` - 修改 API

---

### 32. 数据库路径配置错误处理 [已完成]
**状态**: ✅ 完成

**问题描述**:
- 配置数据库路径后出现 `sqlite3.OperationalError: unable to open database file`
- 需要处理两种情况：
  1. 路径有数据库文件 → 直接加载
  2. 路径没有数据库文件 → 自动创建并重启

**解决方案**:
1. 保存配置时验证 db_path 目录是否可写
2. 强制重启服务（数据库路径变更时不需要用户确认）
3. 重启后 IOCManager 会自动创建新数据库（如果不存在）

**修改文件**:
- [X] `src/web/app.py` - save_config API 添加 db_path 验证逻辑
- [X] `src/web/templates/settings.html` - 保存 db_path 时直接重启
