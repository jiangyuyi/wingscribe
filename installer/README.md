# WingScribe 安装包构建说明

本目录包含 WingScribe Windows 安装包的构建脚本和配置文件。

## 目录结构

```
installer/
├── build.ps1          # 主构建脚本
├── installer.iss      # Inno Setup 安装脚本
├── requirements-cpu.txt # CPU 版本依赖列表
├── assets/            # UI 资源文件（图标、图片）
├── build/             # 构建输出目录（自动生成）
│   ├── python/        # Python 运行时
│   ├── venv/          # 虚拟环境
│   └── src/           # WingScribe 源代码
├── wheels/            # PyTorch wheel 文件（自动下载）
├── tools/             # ExifTool（自动下载）
└── Output/            # 最终安装包输出（ISCC 生成）
```

## 构建步骤

### 前置要求

1. **Windows 10 或更高版本**
2. **Python 3.11+**（用于运行构建脚本）
3. **Inno Setup 6.0+**（用于创建安装包）
4. **稳定的网络连接**（用于下载依赖）

### 安装 Inno Setup

从 [jrsoftware.org](https://jrsoftware.org/isdl.php) 下载并安装 Inno Setup。

### 运行构建

```powershell
# 在项目根目录运行
cd installer
.\build.ps1
```

构建过程将：
1. 下载 Python 3.11.8 嵌入版
2. 下载 PyTorch CPU wheel 文件
3. 下载 ExifTool
4. 创建虚拟环境并安装所有依赖
5. 复制 WingScribe 源代码
6. 创建启动脚本

构建完成后，`build/` 目录将包含所有需要的文件。

### 生成安装包

```powershell
# 在 installer 目录运行
iscc installer.iss
```

最终安装包将生成在 `Output/WingScribe-Setup-{version}.exe`

## 自动构建

推送 tag 到 GitHub 将自动触发构建：

```bash
git tag v1.0.0
git push origin v1.0.0
```

或者手动触发 workflow：
1. 访问 GitHub Actions 页面
2. 选择 "Build Windows Installer"
3. 点击 "Run workflow"
4. 输入版本号

## UI 资源

需要准备以下资源文件（放置在 `assets/` 目录）：

- `app-icon.ico` - 应用图标（推荐 256x256）
- `wizard-side.bmp` - 安装向导侧边图（推荐 164x314）
- `wizard-small.bmp` - 安装向导小图标（推荐 55x55）

可以使用以下工具创建图标：
- [GIMP](https://www.gimp.org/)（免费）
- [Paint.NET](https://www.getpaint.net/)（免费）
- [Inkscape](https://inkscape.org/)（免费，矢量图）

## 故障排除

### Python 下载失败

如果 Python 下载失败，可以手动下载：

```
https://www.python.org/ftp/python/3.11.8/python-3.11.8-embed-amd64.zip
```

然后解压到 `build/python/` 目录。

### pip 安装超时

设置国内镜像源：

```powershell
$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
```

### Inno Setup 编译错误

确保：
1. Inno Setup 版本 >= 6.0
2. 路径中不包含特殊字符
3. 有足够的磁盘空间（至少 2GB）

## 体积优化

当前安装包体积约 550MB，可通过以下方式优化：

1. **使用 UPX 压缩**：压缩所有 .exe 和 .dll 文件
2. **排除不必要的模块**：从 Python 中移除不需要的标准库
3. **优化 PyTorch**：使用更小的 torch 版本

## 许可证

本安装包遵循 WingScribe 项目的 MIT 许可证。

第三方组件许可证：
- Python: PSF License
- PyTorch: BSD-style
- ExifTool: Artistic License
- Inno Setup: Permission-based license
