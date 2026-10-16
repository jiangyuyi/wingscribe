# 安装与使用

所有源码命令从仓库根目录执行。使用 Python 3.11；Windows 安装包内置 Python，无需另建虚拟环境。

## Windows 安装包

从 [项目发布页](https://github.com/jiangyuyi/wingscribe/releases) 选择 `WingScribe-Setup-CPU-<版本>.exe` 或 `WingScribe-Setup-GPU-<版本>.exe`。GPU 包包含 CUDA 12.8 版 PyTorch，面向 NVIDIA CUDA 显卡；实际兼容性需结合驱动和 [发布验收](../development/release-checklist.md) 检查。

安装后通过快捷方式或安装目录的 `scripts/start_web.bat` 启动。启动程序直接使用内置 Python，不复制开发机 venv。打开 `/settings` 配置源目录与输出目录。首次本地推理可能需要下载 BioCLIP 权重，下载量与所选模型有关。

## 源码安装

安装 ExifTool，并验证 `exiftool -ver` 能输出版本。依赖安装和模型下载需要网络。

```powershell
git clone https://github.com/jiangyuyi/wingscribe.git
cd wingscribe
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Linux/macOS 激活环境使用 `source venv/bin/activate`，其余 Python 命令相同。ExifTool 可通过所在系统的软件管理工具安装。

当前源码在启动时就校验配置：没有 `config/settings.yaml` 时，先从 `config/settings.example.yaml` 复制，按 [配置指南](configuration.md) 填入照片源和独立输出目录的合法绝对路径。不要覆盖已有配置。然后执行 `python src/web/app.py --host 127.0.0.1 --port 8000`，打开 `http://127.0.0.1:8000/settings` 继续调整。未配置直接进入设置页的启动流程仍需修正。

名录缺失时先按 [分类数据指南](taxonomy.md) 准备 IOC Excel 和数据库路径，再运行 `python scripts/import_ioc_data.py`。模型预下载入口为 `python scripts/download_model.py`；所下载模型与生产选择应分别核对。

## 首次处理

1. 用少量照片副本验证流程，目录可采用 `20260101_北京` 等可解析日期和地点的名称。
2. 在 `/settings` 确认源、输出和数据库路径；保存后重启使配置生效。
3. 进入 `/admin`，按日期或文件夹启动处理，检查日志和输出结果。
4. 回到图库检查裁切图、原图和 AI 候选，再进行人工校对。

自动流水线可通过 `paths.output.write_back_to_source` 控制原图元数据写回；人工校对当前另有写回逻辑，会尝试修改存在的原图。该差异记录在 [已知问题](../development/status.md)。

命令行批处理：

```powershell
python src/pipeline_runner.py --start 20240101 --end 20240131
```

## 部署脚本

仓库根目录的 `deploy.ps1` / `deploy.sh` 提供安装、配置、更新、启动和后台管理入口。先查看本地脚本帮助，再按需执行：

```powershell
.\deploy.ps1 help
.\deploy.ps1 config
.\deploy.ps1 web
.\deploy.ps1 -d
.\deploy.ps1 -t
.\deploy.ps1 -s
```

Linux/macOS 对应 `bash deploy.sh help`、`bash deploy.sh config`、`bash deploy.sh web` 和 `bash deploy.sh -d/-t/-s`（分别执行）。旧说明中的 `scripts/deploy.sh cloud:config` 并不存在。

## 常见问题

| 现象 | 检查方式 |
| --- | --- |
| 找不到 ExifTool | 在启动程序的同一终端验证 `exiftool -ver`；安装包检查 `tools/` |
| 首次识别慢 | 查看模型下载及文本特征编码日志；后续会使用缓存 |
| CUDA 不可用 | 运行 `python scripts/check_gpu.py`，核对实际 Python/PyTorch 环境；CPU wheel 不会启用 CUDA |
| 显存不足 | 可改用 `processing.device: cpu`；当前流水线尚未实际应用 `local.inference_batch_size` 分批，不能依靠调小该字段解决 |
| 图片不显示或源目录不可见 | 核对绝对路径、挂载状态以及运行账户权限；多源路径见 [架构](../development/architecture.md) |
| 中文目科属缺失 | 检查 [分类映射文件](taxonomy.md)，不要运行已删除的一次性修复脚本 |

备份脚本位于 `scripts/backup_db.ps1` 和 `scripts/backup_db.sh`；执行前查看参数及目标目录。数据库备份不等于照片备份。
