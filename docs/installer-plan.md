# WingScribe Windows 安装包制作计划（历史方案）

> 本文记录早期 CPU-only 安装包的设计过程，不代表当前发布能力。当前项目已提供 CPU/GPU 双安装包，GPU 包使用 CUDA 12.8 版 PyTorch 并支持 RTX 50 系列；请以 [安装器构建指南](../installer/README.md) 和 [README](../README.md) 为准。

## 项目概述

将 WingScribe 的 PowerShell 部署脚本转换为独立的 Windows 安装包（EXE/MSI），包含所有依赖，仅支持 CPU 模式。

## 技术方案对比

### 方案 A: Inno Setup + PyInstaller（推荐）

**优点：**
- 成熟稳定，广泛使用
- 支持中文界面
- 可创建自定义安装向导
- 安装包体积相对较小
- GitHub Actions 支持良好

**缺点：**
- 需要编写 ISS 脚本
- 学习曲线稍陡

### 方案 B: NSIS

**优点：**
- 完全免费开源
- 高度可定制
- 插件生态丰富

**缺点：**
- 脚本语法较复杂
- 中文支持需要额外配置

### 方案 C: WiX Toolset (MSI)

**优点：**
- 微软官方工具
- 创建标准 MSI 包
- 支持企业部署

**缺点：**
- 学习曲线陡峭
- XML 配置复杂
- 不适合快速开发

### 方案 D: PyInstaller 单文件 EXE

**优点：**
- 最简单的方式
- 纯 Python 生态

**缺点：**
- PyTorch 打包困难
- 启动慢（需要解压）
- 体积巨大（>2GB）
- ExifTool 难以集成

## 推荐方案：Inno Setup + 预打包虚拟环境

### 架构设计

```
WingScribe-Setup.exe
├── Inno Setup 安装程序
├── 预打包内容
│   ├── Python 3.11 嵌入版 (或便携版)
│   ├── 预安装的虚拟环境
│   │   ├── PyTorch CPU 版本
│   │   ├── YOLOv11 模型文件
│   │   ├── BioCLIP 模型缓存
│   │   └── 所有 pip 依赖
│   ├── ExifTool 可执行文件
│   ├── WingScribe 源代码
│   ├── 配置文件模板
│   └── 启动脚本
└── 卸载程序
```

### 关键组件清单

#### 1. Python 运行时
- **方案选择**: Python 3.11 便携版（非嵌入版）
- **来源**: python.org 官方 Windows embeddable package
- **理由**: 嵌入版缺少 pip 和某些标准库，便携版更完整

#### 2. PyTorch CPU 版本
- **版本**: 2.1+ CPU-only
- **安装方式**: 预先下载 wheel 文件
- **wheel 文件**:
  - torch-2.1.0+cpu-cp311-cp311-win_amd64.whl
  - torchvision-0.16.0+cpu-cp311-cp311-win_amd64.whl
  - torchaudio-2.1.0+cpu-cp311-cp311-win_amd64.whl
- **下载地址**: https://download.pytorch.org/whl/cpu/torch_stable.html

#### 3. ExifTool
- **版本**: 最新稳定版
- **文件**: exiftool.exe
- **来源**: https://exiftool.org/
- **许可证**: 免费可分发

#### 4. YOLOv11 模型
- **模型**: yolov26n.pt（轻量级）
- **自动下载**: 首次运行时从 ultralytics 下载
- **预缓存**: 可选择打包进去

#### 5. BioCLIP 模型
- **问题**: 模型文件巨大（>500MB）
- **解决方案**: 首次运行时自动下载
- **缓存位置**: data/models/

#### 6. 其他 Python 依赖
- 来自 requirements.txt（排除 torch、testing 依赖）
- 预先安装到虚拟环境中

### 安装流程设计

#### 用户安装向导步骤

1. **欢迎页面**
   - 显示 WingScribe logo 和简介
   - 中英文双语

2. **许可协议**
   - MIT 许可证
   - 第三方组件许可列表

3. **选择安装位置**
   - 默认: `C:\Program Files\WingScribe`
   - 或 `C:\Users\{user}\WingScribe`（无需管理员权限）

4. **选择组件**
   - [必选] 主程序
   - [可选] 桌面快捷方式
   - [可选] 开机自启动服务

5. **配置向导**（安装后首次运行）
   - 选择照片目录
   - 选择输出目录
   - 配置 Web 服务端口

6. **安装进度**
   - 显示解压进度条
   - 预计时间: 1-3 分钟

7. **完成页面**
   - 启动选项：立即启动 Web 服务
   - 显示访问地址：http://localhost:8000

### 卸载流程

1. 停止运行中的服务
2. 删除程序文件
3. 删除用户数据（可选保留配置和数据）
4. 删除快捷方式
5. 清理注册表（如有）

## 文件结构

### 源代码结构（安装包内）

```
WingScribe/
├── python/              # Python 运行时
│   ├── python.exe
│   ├── DLLs/
│   ├── Lib/
│   └── Scripts/
├── venv/                # 预配置虚拟环境
│   ├── Lib/site-packages/
│   │   ├── torch/       # CPU-only PyTorch
│   │   ├── ultralytics/
│   │   ├── open_clip/
│   │   └── ...
│   └── Scripts/
│       └── pip.exe
├── src/                 # WingScribe 源代码
├── config/              # 配置模板
├── tools/               # 工具程序
│   └── exiftool.exe
├── scripts/             # 启动脚本
│   ├── start_web.bat
│   ├── start_web.ps1
│   └── uninstall_helper.ps1
├── data/                # 数据目录（运行时创建）
│   ├── db/
│   ├── models/          # AI 模型缓存
│   ├── processed/       # 输出目录
│   └── references/      # IOC 鸟类名录
└── README.txt           # 用户说明
```

## GitHub Actions 工作流

### 构建流程

```yaml
# .github/workflows/build-installer.yml
name: Build Windows Installer

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest

    steps:
      # 1. 设置环境
      - name: Checkout code
        uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      # 2. 下载工具
      - name: Download Inno Setup
        run: |
          # 下载 ISCC.exe

      # 3. 准备 Python 依赖
      - name: Create virtual environment
        run: |
          python -m venv build/venv

      - name: Download PyTorch CPU wheels
        run: |
          # 下载预编译的 CPU-only wheels

      - name: Install dependencies
        run: |
          build/venv/Scripts/pip install --no-index --find-links=wheels/ -r requirements-cpu.txt

      # 4. 下载 ExifTool
      - name: Download ExifTool
        run: |
          # 从官方源下载

      # 5. 准备源代码
      - name: Prepare source files
        run: |
          # 复制源代码到 build 目录

      # 6. 生成安装包
      - name: Build installer
        run: |
          iscc installer.iss

      # 7. 发布 Release
      - name: Upload to Release
        uses: softprops/action-gh-release@v1
        with:
          files: Output/WingScribe-Setup.exe
```

## 安装包体积估算

| 组件 | 体积 |
|------|------|
| Python 3.11 便携版 | ~25 MB |
| PyTorch CPU | ~150 MB |
| torchvision | ~50 MB |
| 其他 pip 包 | ~300 MB |
| ExifTool | ~5 MB |
| YOLOv11 模型 | ~10 MB（可选预打包） |
| WingScribe 源代码 | ~2 MB |
| **总计（不含 BioCLIP）** | **~550 MB** |
| BioCLIP 模型 | ~500 MB（首次运行下载） |
| **完整安装后** | **~1.05 GB** |

## requirements-cpu.txt

```
# CPU 版本依赖（排除 GPU 相关）
ultralytics
opencv-python
Pillow
transformers
torch==2.1.0+cpu
torchvision==0.16.0+cpu
requests
PyExifTool
fastapi
uvicorn[standard]
jinja2
python-multipart
sqlalchemy
pandas
pyyaml
openpyxl
websockets
open-clip-torch
httpx
pydantic
```

## Inno Setup 脚本大纲

```iss
; installer.iss
[Setup]
AppName=WingScribe
AppVersion=1.0.0
DefaultDirName={autopf}\WingScribe
DefaultGroupName=WingScribe
OutputDir=Output
OutputBaseFilename=WingScribe-Setup
Compression=lzma2
SolidCompression=yes
WizardImageFile=assets\sidebar.bmp
WizardSmallImageFile=assets\wizard.bmp

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Python 运行时
Source: "build\python\*"; DestDir="{app}\python"; Flags: ignoreversion recursesubdirs
; 虚拟环境
Source: "build\venv\*"; DestDir="{app}\venv"; Flags: ignoreversion recursesubdirs
; 源代码
Source: "src\*"; DestDir="{app}\src"; Flags: ignoreversion recursesubdirs
; ExifTool
Source: "tools\exiftool.exe"; DestDir="{app}\tools"
; 启动脚本
Source: "scripts\*"; DestDir="{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{group}\WingScribe"; Filename: "{app}\scripts\start_web.bat"
Name: "{commondesktop}\WingScribe"; Filename: "{app}\scripts\start_web.bat"

[Run]
Filename: "{app}\scripts\first_run.exe"; Description: "启动配置向导"; Flags: postinstall shellexec skipifsilent
```

## 首次运行配置程序

创建一个简单的 Python GUI 程序（使用 tkinter 或 PyQt）：

```python
# scripts/first_run.py
import tkinter as tk
from tkinter import filedialog, messagebox
import yaml
import os

class ConfigWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WingScribe 配置向导")
        self.setup_ui()

    def setup_ui(self):
        # 欢迎页面
        # 照片目录选择
        # 输出目录选择
        # 端口配置
        # 完成按钮

    def save_config(self):
        # 生成 settings.yaml
        pass

if __name__ == "__main__":
    app = ConfigWizard()
    app.root.mainloop()
```

## 待确认问题

1. **安装方式**:
   - [ ] EXE（Inno Setup，推荐）
   - [ ] MSI（WiX）
   - [ ] 便携版 ZIP（绿色版）

2. **Python 版本**:
   - [ ] 3.11（当前推荐）
   - [ ] 3.12（最新稳定）

3. **模型预打包**:
   - [ ] 预打包 BioCLIP 模型（增加 500MB）
   - [ ] 首次运行时下载（节省体积）

4. **安装位置**:
   - [ ] Program Files（需要管理员权限）
   - [ ] 用户目录（无需管理员权限，推荐）

5. **服务启动方式**:
   - [ ] Windows 服务（后台运行）
   - [ ] 开机自启动（注册表 Run 键）
   - [ ] 仅手动启动

6. **数据目录**:
   - [ ] 与程序安装在同一目录
   - [ ] 分离到用户文档目录

## 实施步骤

### 阶段 1: 准备工作（1-2 天）
- [ ] 确定最终技术方案
- [ ] 创建 build 目录结构
- [ ] 准备 Inno Setup 脚本
- [ ] 创建 requirements-cpu.txt

### 阶段 2: 自动化构建（2-3 天）
- [ ] 编写 GitHub Actions 工作流
- [ ] 创建构建脚本（build.ps1）
- [ ] 测试本地构建
- [ ] 优化压缩和体积

### 阶段 3: 安装程序（2-3 天）
- [ ] 设计安装向导 UI
- [ ] 编写配置向导程序
- [ ] 创建启动脚本
- [ ] 编写卸载脚本

### 阶段 4: 测试与发布（1-2 天）
- [ ] 在干净 Windows 系统上测试
- [ ] 修复发现的 bug
- [ ] 创建第一个 Release
- [ ] 编写用户文档

## 参考资料

- [Inno Setup 官方文档](https://jrsoftware.org/isinfo.php)
- [PyTorch CPU wheel 下载](https://download.pytorch.org/whl/cpu/torch_stable.html)
- [Python Windows Embeddable Package](https://www.python.org/downloads/windows/)
- [ExifTool 官方网站](https://exiftool.org/)
