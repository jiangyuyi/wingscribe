# WingScribe Installer Build Guide

本目录用于构建 Windows 安装包（CPU/GPU 双版本）。

## 目录说明

- `build.ps1`: 构建脚本（准备运行时、依赖、源码、自检）
- `installer.iss`: CPU 安装包 Inno Setup 脚本
- `installer-gpu.iss`: GPU 安装包 Inno Setup 脚本
- `requirements-cpu.txt` / `requirements-gpu.txt`: 依赖清单
- `wheels-cpu/` / `wheels-gpu/`: PyTorch 本地 wheel 缓存
- `models/`: 预置模型（必须包含 `yolo26n.pt`）
- `tools/`: ExifTool 运行时（`exiftool.exe` + `exiftool_files/`）
- `build-cpu/` / `build-gpu/`: 构建输出目录（自动生成）
- `Output/`: 最终安装包输出目录

## 前置要求

1. Windows 10/11
2. PowerShell 可执行脚本（或使用 `-ExecutionPolicy Bypass`）
3. Inno Setup 6.x（`ISCC.exe`）
4. 首次构建需要网络下载依赖；后续可走缓存快速构建

## 标准构建流程

### CPU

```powershell
cd installer
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Mode cpu -Version 1.0.0
iscc .\installer.iss
```

产物：`Output/WingScribe-Setup-CPU-<version>.exe`

### GPU

```powershell
cd installer
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Mode gpu -Version 1.0.0
iscc .\installer-gpu.iss
```

产物：`Output/WingScribe-Setup-GPU-<version>.exe`

GPU 包使用 CUDA 12.8 版 PyTorch，以支持 RTX 50 系列（Blackwell）。本地构建可通过参数指定兼容的 wheel 镜像：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Mode gpu -Version 1.0.0 -PyTorchWheelBase https://mirrors.nju.edu.cn/pytorch/whl
```

## 本地快速回归（强烈推荐）

当你只改脚本/逻辑，不改依赖时，避免重复下载和安装：

```powershell
cd installer
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Mode cpu -SkipWheels -SkipExifTool -SkipPython -SkipDepsInstall
```

GPU 同理：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Mode gpu -SkipWheels -SkipExifTool -SkipPython -SkipDepsInstall
```

说明：
- `-SkipDepsInstall`: 跳过 pip 安装（依赖不变时可大幅提速）
- `-RefreshWheels`: 强制清理并重下 torch wheel（仅在怀疑缓存损坏时使用）

## 内置自检内容

`build.ps1` 会在打包前执行：

1. `import torch, fastapi, uvicorn`
2. 加载 `data/models/yolo26n.pt`
3. 检查 Web 静态资源（bootstrap/css/js/favicon）
4. 运行 `scripts/start_web.bat --self-test`

任何一步失败都会中止构建。

## 常见问题

### 1) 长时间“看起来卡住”（CPU/磁盘占用低）

通常卡在外部依赖下载或 pip 网络等待，不是编译器卡死。建议先用 `-Skip*` 快速构建验证逻辑。

### 2) `Expected wheel not found`

说明 `wheels-cpu/` 或 `wheels-gpu/` 缺少与当前脚本版本匹配的 wheel。补齐后重试，或执行 `-RefreshWheels`。

### 3) PowerShell 执行策略报错

使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 ...
```

### 4) GPU 包体积大

GPU 包包含 CUDA 版 PyTorch 及相关运行时，体积显著大于 CPU 包，属于预期。

## 版本与命名

- `build.ps1 -Version <x.y.z>` 会写入 `installer/version.txt`
- `.iss` 通过 `AppVersion` 生成同版本文件名
- 需保证构建参数版本号与发布版本一致（本地/CI 同规则）
