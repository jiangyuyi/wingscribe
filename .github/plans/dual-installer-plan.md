# 计划：构建 CPU + GPU 双版本安装包

## 背景

用户希望每次执行 GitHub Actions 时同时生成两个安装包：
1. **CPU 版本** - 使用 PyTorch CPU 版本，无需显卡
2. **GPU 版本** - 使用 PyTorch CUDA 版本，需要 NVIDIA 显卡

## 现状分析

### 当前架构
- `installer/build.ps1` - 构建脚本
  - `Download-PyTorchWheels` - 下载 PyTorch CPU wheels
  - `Install-Dependencies` - 使用 `requirements-cpu.txt` 安装依赖
- `installer/requirements-cpu.txt` - CPU 版本依赖
- `.github/workflows/build-installer.yml` - GitHub Actions 工作流
- `installer/installer.iss` - Inno Setup 脚本

### 关键区别

| 组件 | CPU 版本 | GPU 版本 |
|------|----------|----------|
| PyTorch | `torch-2.4.0+cpu-cp311-*.whl` | `torch-2.4.0+cu118-cp311-*.whl` |
| torchvision | `torchvision-0.19.0+cpu-cp311-*.whl` | `torchvision-0.19.0+cu118-cp311-*.whl` |
| requirements | `requirements-cpu.txt` | `requirements-gpu.txt` (需创建) |
| 安装包 | `WingScribe-Setup-CPU-x.x.x.exe` | `WingScribe-Setup-GPU-x.x.x.exe` |
| ISS 脚本 | `installer.iss` | `installer-gpu.iss` (需创建) |

## 实现计划

### 步骤 1：创建 GPU 依赖文件

创建 `installer/requirements-gpu.txt`，内容与 `requirements-cpu.txt` 相同，但需要注释说明 GPU 版本需要 CUDA。

### 步骤 2：修改 build.ps1

添加 GPU 模式支持：

```powershell
param(
    [switch]$SkipWheels = $false,
    [switch]$SkipExifTool = $false,
    [switch]$SkipPython = $false,
    [ValidateSet("cpu", "gpu")]
    [string]$Mode = "cpu"  # 新增参数
)
```

修改 `Download-PyTorchWheels` 函数，根据 `$Mode` 参数下载不同的 wheels：
- CPU: `https://download.pytorch.org/whl/cpu/...`
- GPU: `https://download.pytorch.org/whl/cu118/` 或 `cu121`

修改 `Install-Dependencies` 函数，根据 `$Mode` 选择不同的 requirements 文件。

修改输出目录结构：
- CPU: `installer/build-cpu/...`
- GPU: `installer/build-gpu/...`

### 步骤 3：创建 GPU 版本的 Inno Setup 脚本

复制 `installer/installer.iss` 为 `installer/installer-gpu.iss`，修改输出文件名。

### 步骤 4：修改 GitHub Actions 工作流

使用矩阵策略同时构建两个版本：

```yaml
jobs:
  build:
    strategy:
      matrix:
        mode: [cpu, gpu]
    steps:
      - name: Run build script
        run: .\installer\build.ps1 -Mode ${{ matrix.mode }}
      - name: Build installer
        run: |
          $iss = ".\installer\installer.iss"
          if ("${{ matrix.mode }}" -eq "gpu") {
            $iss = ".\installer\installer-gpu.iss"
          }
          & $iscc /DAppVersion=$version /DCPU_MODE=${{ matrix.mode }} $iss
```

### 步骤 5：更新 Release 说明

在 Release body 中同时包含两个安装包的下载链接和说明。

## 关键文件修改

1. **新增**: `installer/requirements-gpu.txt`
2. **修改**: `installer/build.ps1` - 添加 -Mode 参数和 GPU 支持
3. **新增**: `installer/installer-gpu.iss`
4. **修改**: `.github/workflows/build-installer.yml` - 矩阵构建

## 验证方式

1. 本地运行 `.\installer\build.ps1 -Mode cpu` 和 `.\installer\build.ps1 -Mode gpu`
2. 确认两个输出目录 `build-cpu` 和 `build-gpu` 都有正确的虚拟环境
3. GitHub Actions 运行后，检查两个安装包都正确生成
4. Release 包含两个安装包的下载链接
