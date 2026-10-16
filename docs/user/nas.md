# NAS 网络照片目录

WingScribe 使用操作系统提供的本地路径访问 NAS，没有独立的 SMB/WebDAV 存储后端。

先通过 Windows“映射网络驱动器”、macOS“连接服务器”或 Linux 的挂载工具连接共享目录。示例 SMB 地址为 `\\192.168.1.100\Photos` 或 `smb://192.168.1.100/Photos`。WebDAV 是否可挂载取决于系统客户端配置。

启动 WingScribe 前，确认同一运行账户能访问挂载路径。后台进程未必能看到交互登录账户的映射盘。

```yaml
paths:
  sources:
    - path: "Z:/Raw_Birds"
      recursive: true
      enabled: true
  output:
    root_dir: "D:/Birds/Output"
    structure_template: "{source_structure}/{filename}_{species_cn}_{confidence}"
    write_back_to_source: false
  db_path: "data/db/wingscribe.db"
```

Linux/macOS 将源路径替换为实际挂载位置，例如 `/mnt/nas_photos/Raw_Birds` 或 `/Volumes/Photos/Raw_Birds`。源和输出都使用绝对路径；不再通过旧 `base_dir` 拼接相对源目录。其余配置保留，见 [配置指南](configuration.md)。

数据库建议留在本地磁盘；照片输出可以放本地或已挂载共享目录。网络性能、读写权限与断线会影响扫描、裁切和元数据写入。人工校对会写原图的现有限制同样适用于 NAS。
