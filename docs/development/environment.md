# 开发环境与依赖基线

依赖定义在 `pyproject.toml`，精确版本及下载校验在 `uv.lock`。本阶段支持 Python 3.11/3.12、Windows/Linux；本机实际使用 Python 3.12.10。CPU 与 NVIDIA CUDA 环境必须显式选择，不能同时启用。

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/) 后，在仓库根目录执行：

```powershell
# 本机 RTX 5060 使用 CUDA 12.8 构建，不需要另装完整 CUDA Toolkit
uv sync --locked --extra cu128
uv run --locked --extra cu128 python -m pytest

# 无 NVIDIA GPU 或 CI 使用 CPU 环境
uv sync --locked --extra cpu
uv run --locked --extra cpu python -m pytest
```

`uv sync` 默认安装 dev 组。发布环境可加 `--no-dev`。旧 `venv` 不再用于本分支开发；不要激活失效的旧环境，也不要把项目依赖安装到系统 Python。

当前保留 PyTorch 2.10.0、torchvision 0.25.0、Ultralytics 8.4.14 作为恢复基线；模型升级另行验证。NumPy 暂维持 1.26 系列，OpenCV 低于 4.12，避免恢复环境时同时改变数组兼容性。其他直接依赖限定主要版本，精确版本由锁文件固定。显式 PyTorch 索引遵循 [uv 官方说明](https://docs.astral.sh/uv/guides/integration/pytorch/)。

根 `requirements.txt` 和安装器依赖仍是旧入口，尚未完成统一，不用于此次可复现环境验收；B7 将替换安装器消费方式。更新依赖必须重新运行测试并提交锁文件，不能只改版本范围。

测试的 Web 导入使用临时配置与数据库；传统集成测试仅使用已经存在的 `installer/models/yolo26n.pt`，缺少权重则明确跳过，不在测试中下载模型。全部运行结果见 [实施记录](execution-log.md)。自动测试不能代替真实鸟类识别精度、NAS 实机和安装器验收。

ExifTool 是独立可执行文件，Python 的 PyExifTool 包不包含它。仓库已有 `installer/tools/exiftool.exe`，开发时可设置：

```powershell
$env:EXIFTOOL_PATH = (Resolve-Path installer/tools/exiftool.exe).Path
```
