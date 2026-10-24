# WingScribe Installer Build Guide

本目录用于构建 Windows 安装包（CPU/GPU 双版本）。

## 目录说明

- `build.ps1`: 构建脚本（准备运行时、依赖、源码、自检）
- `installer.iss`: CPU 安装包 Inno Setup 脚本
- `installer-gpu.iss`: GPU 安装包 Inno Setup 脚本
- `locks/cpu.txt` / `locks/cu128.txt`: 从 uv.lock 导出的带哈希运行依赖；requirements-cpu/gpu.txt 仅为兼容入口
- `wheels-cpu/` / `wheels-gpu/`: 完整运行依赖 wheel 缓存（两者可复用相同文件）
- `models/`: 预置模型（必须包含 `yolo26n.pt`）
- `tools/`: ExifTool 运行时（`exiftool.exe` + `exiftool_files/`）
- `build-cpu/` / `build-gpu/`: 构建输出目录（自动生成）
- `Output/`: 最终安装包输出目录

## 前置要求

1. Windows 10/11
2. PowerShell 可执行脚本（或使用 `-ExecutionPolicy Bypass`）
3. Windows Python 3.11（含 pip，作为构建工具）；可用 `-BuildPython <python.exe绝对路径>` 指定；Inno Setup 6.x（`ISCC.exe`）
4. 首次构建需要网络下载依赖；后续可走缓存快速构建

## 标准构建流程

以下 `1.0.0` 仅为示例，构建与编译必须替换成相同的目标版本。直接运行 `iscc` 不会自动读取 `version.txt`，须显式传 `/DAppVersion`。

### CPU

```powershell
cd installer
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Mode cpu -Version 1.0.0
iscc /DAppVersion=1.0.0 .\installer.iss
```

产物：`Output/WingScribe-Setup-CPU-<version>.exe`

### GPU

```powershell
cd installer
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Mode gpu -Version 1.0.0
iscc /DAppVersion=1.0.0 .\installer-gpu.iss
```

产物：`Output/WingScribe-Setup-GPU-<version>.exe`

GPU 包使用 CUDA 12.8 版 PyTorch，CPU/GPU 均遵循 uv.lock 的固定版本。下载器先验证离线缓存，再使用南京大学 PyTorch 镜像及清华 PyPI 镜像，国内镜像显式直连、不继承本机代理；镜像失败才明确回退官方来源。完成全量哈希校验后离线安装，不使用开发机的 pip 配置。

`-PyTorchWheelBase` 自定义地址和 `-RefreshWheels` 整批清缓存已停用；损坏缓存会自动改名保留证据，再下载相同锁定版本。更新依赖后先运行 `python scripts/export_installer_lock.py --uv <uv路径>`，再构建。

源码载荷只包含配置样例、明确列出的运行脚本、参考名录和文档；不会打包 config/settings.yaml、secrets.yaml 或重置数据库脚本。再次暂存会清理生成目录中的旧配置。payload-manifest.json 记录所复制文件的 SHA-256。

当前已接入载荷、锁定依赖及固定运行时；Python 3.11.8/pip 25.0.1 下载使用国内镜像直连及上游摘要，ExifTool 13.40 使用仓库固定归档。SkipPython/SkipExifTool 仍逐文件校验缓存；工具源归档保存在 installer/tools，打包使用各 build/tools。旧版升级卸载日志仍需专项验证，**暂未完成整包安装验收**，以 [B7 计划](../docs/development/b7-packaging-plan.md) 为准。

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
- `-SkipDepsInstall`: 跳过安装，但仍按所选锁文件检查所有运行依赖版本与 PyTorch 变体；旧缓存不匹配会失败。
- `-SkipWheels`: 只跳过下载；安装仍离线校验完整缓存及哈希，缺包时中止。

## 内置自检内容

`build.ps1` 会在打包前执行：

1. 核验运行时与 CPU/cu128 锁的版本一致，再 `import torch, fastapi, uvicorn`
2. 加载 `data/models/yolo26n.pt`
3. 检查 Web 静态资源（bootstrap/css/js/favicon）
4. 运行 `scripts/start_web.bat --self-test`

任何一步失败都会中止构建。

## 常见问题

### 1) 长时间“看起来卡住”（CPU/磁盘占用低）

通常卡在外部依赖下载或 pip 网络等待，不是编译器卡死。建议先用 `-Skip*` 快速构建验证逻辑。

### 2) `Expected wheel not found`

说明 `wheels-cpu/` 或 `wheels-gpu/` 缺少与当前脚本版本匹配的 wheel。使用锁定下载器补齐后重试；不要整批删除已验证缓存。

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

## 发布与素材

CPU/GPU 共用 [发布验收清单](../docs/development/release-checklist.md)。当前运行时是 embedded Python 加预装依赖，不打包开发机 venv。

快捷方式图标引用 `src/web/static/favicon.ico`；现有 `.iss` 未引用旧素材说明中的 `assets/app-icon.ico`、`wizard-side.bmp` 或 `wizard-small.bmp`，这些不作为构建必需文件。

根 README 的完整文档在 [项目仓库](https://github.com/jiangyuyi/wingscribe/tree/master/docs)，当前构建按载荷白名单包含离线 docs 目录。

## 启动与配置

BAT/PowerShell 均调用 scripts/launch_web.py；首次配置由 Web 页面完成，启动时不自动修复、覆盖 settings.yaml 或创建 secrets.yaml。可传 --host/--port；--self-test 创建应用检查但不监听端口。模型库偏好写入应用 data/runtime-config。旧 init_env.py 不再随安装载荷发布。


## 安装器隔离验收

编译测试包传 `/DValidationBuild=1 /DAppVersion=0.0.0.3`。测试包使用独立 AppId，不写卸载注册项、不创建快捷方式、不自动启动应用；为缩短重复验证时间，测试模式无压缩并允许分卷，`.exe` 与全部 `.bin` 必须放在同一目录。它不是发布包。正式模式保留 lzma2 压缩。

打包模型仅包含指纹已校验的 `yolo26n.pt`，不会递归收集 BioCLIP 缓存、下载分片或实验文件。BioCLIP 安装获取仍按模型配置流程单独完成。

新安装器用 `installer-format.txt` 标记安全日志代际。若目标目录有旧卸载日志且没有匹配标记，则拒绝覆盖；应先备份配置和数据、使用新的空目录，不能先执行旧卸载器。该保护不等于旧安装目录自动迁移完成。


编译成功后记录文件摘要：

```powershell
python scripts/installer_artifacts.py --directory installer/Output --mode cpu --version 1.2.3
python scripts/installer_artifacts.py --verify installer/Output/WingScribe-Setup-CPU-1.2.3.sha256.json
```

清单包含 EXE 与同版本已生成分卷的大小和 SHA-256；先确认编译成功，再生成清单。它用于检查传输完整性，不是发行者签名。CI 保留清单并随正式发布附上。

GPU 正式包采用 lzma2 压缩分卷：下载同版本 EXE、全部 `-N.bin` 和 SHA-256 清单，放在同一目录后启动 EXE。不要仅保留 EXE。CPU 正式包仍为单 EXE。
