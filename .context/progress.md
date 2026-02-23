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

### 1. 移除 Docker 相关功能 [待开始]
**目标**: 彻底删除所有 Docker 部署代码，回归纯本地运行模式

**待删除文件**:
- `Dockerfile.cpu`
- `Dockerfile.gpu`
- `Dockerfile.webui`
- `docker-compose.yml`
- `docker-compose.split.yml`
- `docker-compose.remote.yml`
- `docker-compose.dev.yml`
- `docker-compose.split.dev.yml`
- `scripts/docker-entrypoint.sh`

**待修改文件**:
- `README.md` - 移除所有 Docker 相关章节

---

### 2. 修复物种列表分类显示问题 [待开始]
**问题**: 物种列表只显示拉丁名，不显示中文名

**可能原因**:
- 数据库中 `chinese_name` 字段为空
- 前端渲染逻辑问题

**排查步骤**:
1. 检查数据库中 taxonomy 表是否有中文名数据
2. 检查前端 `index.html` 渲染逻辑
3. 检查 `ioc_manager.py` 返回的数据结构

---

### 3. 升级 YOLO 到 v11 [待开始]
**目标**: 将 YOLOv8 升级到 YOLOv11

**修改文件**:
- `src/core/detector.py` - 更新模型名称和导入

---

### 4. 切换数据库到 MySQL [待开始]
**目标**: 从 SQLite 迁移到 MySQL，支持远程访问

**推荐**: MySQL 或 PostgreSQL

**修改文件**:
- `src/metadata/ioc_manager.py` - 修改数据库连接逻辑
- `config/settings.yaml` - 添加数据库配置项

---

### 5. 创建精简版 Docker (仅浏览) [待开始]
**目标**: 创建仅包含 Web 浏览功能的轻量级 Docker

**功能范围**:
- 照片浏览
- 分类筛选
- 物种搜索

**不包含**:
- YOLO 检测
- BioCLIP 识别
- Pipeline 执行

