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
- [X] 提交: `59a2213`

---

### 3. 修复 deploy.ps1 路径问题 [已完成]
**状态**: ✅ 完成

- [X] 将 deploy.ps1 从 scripts/ 移到项目根目录
- [X] 将 deploy.sh 从 scripts/ 移到项目根目录
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

### 6. 升级 YOLO 到 v11 [待开始]
**目标**: 将 YOLOv8 升级到 YOLOv11

**修改文件**:
- `src/core/detector.py` - 更新模型名称和导入

---

### 7. 切换数据库到 MySQL [待开始]
**目标**: 从 SQLite 迁移到 MySQL，支持远程访问

**推荐**: MySQL 或 PostgreSQL

**修改文件**:
- `src/metadata/ioc_manager.py` - 修改数据库连接逻辑
- `config/settings.yaml` - 添加数据库配置项

---

### 8. 创建精简版 Docker (仅浏览) [待开始]
**目标**: 创建仅包含 Web 浏览功能的轻量级 Docker

**功能范围**:
- 照片浏览
- 分类筛选
- 物种搜索

---

### 9. 修复裁切图片路径重复和前端显示问题 [已完成]
**状态**: ✅ 完成

**问题**:
- 输出路径出现 `clip/clip` 重复
- 前端无法正常显示裁切后的图片

**原因分析**:
- 配置文件 `output.root_dir` 设置为 `Y:/1按年份/2026/clip`
- 源文件路径结构包含 `clip` 文件夹（如 `Y:/1按年份/2026/clip/20260110...`）
- `source_structure` 保留了完整路径结构，导致路径重复

**修复方案**:
- [X] 修改配置：`output.root_dir` 从 `clip` 改为 `processed`
- [X] 修复 `app.py` 中绝对路径处理逻辑
- [X] 提交: 准备中
