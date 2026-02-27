# NAS 网络存储设置指南 (WebDAV / SMB)

飞羽志 (WingScribe) 通过 **操作系统级挂载** 支持网络存储（NAS）。这意味着您可以将远程驱动器（WebDAV 或 Samba/SMB）挂载为本地盘符（Windows）或目录（macOS/Linux），然后像使用本地文件夹一样配置飞羽志。

## 1. 挂载远程驱动器

### Windows
1.  打开 **文件资源管理器**。
2.  右键点击 **此电脑** -> **映射网络驱动器...**
3.  **驱动器**: 选择一个盘符（例如 `Z:`）。
4.  **文件夹**: 
    *   **SMB**: `\\192.168.1.100\Photos`
    *   **WebDAV**: `http://192.168.1.100:5005` (确保系统 "WebClient" 服务已启动)。
5.  勾选 "登录时重新连接"。
6.  点击 **完成**。

### macOS
1.  在 Finder 中，点击菜单栏的 **前往** -> **连接服务器** (快捷键 Cmd+K)。
2.  输入地址:
    *   **SMB**: `smb://192.168.1.100/Photos`
    *   **WebDAV**: `http://192.168.1.100:5005`
3.  点击 **连接**。
4.  驱动器将挂载在 `/Volumes/Photos`。

### Linux
使用 `mount` 命令或桌面环境的文件管理器。
示例 (使用 cifs 挂载 SMB):
```bash
sudo mount -t cifs -o username=user,password=pass //192.168.1.100/Photos /mnt/nas_photos
```

## 2. 配置飞羽志 (WingScribe)

编辑 `config/settings.yaml`。设置 `base_dir` 为挂载路径，并添加扫描源。

### 示例：Windows (映射为 Z 盘)
```yaml
paths:
  # 基础目录（挂载路径）
  base_dir: "Z:/"

  # 添加为扫描源
  sources:
    - path: "Raw_Birds"
      recursive: true
```

### 示例：macOS/Linux
```yaml
paths:
  base_dir: "/Volumes/Photos"

  sources:
    - path: "2024_Birds"
      recursive: true
```

## 3. 重启应用
修改 `settings.yaml` 后，重启飞羽志 Web 服务以使配置生效：
```bash
python src/web/app.py
```

## 常见问题
*   **权限问题**: 请确保运行 `python` 的用户对挂载的目录拥有"读取"和"写入"权限。
*   **性能**: 网络存储的扫描速度取决于网络带宽。对于包含数万张照片的目录，首次扫描可能较慢。
*   **挂载稳定性**: 建议在系统启动后手动验证网络驱动器是否已挂载，再启动 WingScribe。
