# NAS Setup Guide (WebDAV / SMB)

FeatherTrace supports network storage (NAS) via **OS-level mounting**. This means you mount your remote drive (WebDAV or Samba/SMB) as a local drive letter (Windows) or directory (macOS/Linux), and then configure FeatherTrace to use that path.

## 1. Mount Remote Drive

### Windows
1.  Open **File Explorer**.
2.  Right-click **This PC** -> **Map network drive...**
3.  **Drive**: Choose a letter (e.g., `Z:`).
4.  **Folder**: 
    *   **SMB**: `\\192.168.1.100\Photos`
    *   **WebDAV**: `http://192.168.1.100:5005` (Requires "WebClient" service running).
5.  Check "Reconnect at sign-in".
6.  Click **Finish**.

### macOS
1.  Finder -> **Go** -> **Connect to Server** (Cmd+K).
2.  Enter address:
    *   **SMB**: `smb://192.168.1.100/Photos`
    *   **WebDAV**: `http://192.168.1.100:5005`
3.  Click **Connect**.
4.  The drive will be mounted at `/Volumes/Photos`.

### Linux
Use `mount` command or your desktop environment's file manager.
Example (SMB via cifs):
```bash
sudo mount -t cifs -o username=user,password=pass //192.168.1.100/Photos /mnt/nas_photos
```

## 2. Configure FeatherTrace

Edit `config/settings.yaml`. Set `base_dir` to the mounted path, and add sources for scanning.

### Example: Windows (Drive Z:)
```yaml
paths:
  # Base directory (mounted path)
  base_dir: "Z:/"

  # Add as a source
  sources:
    - path: "Raw_Birds"
      recursive: true
```

### Example: macOS/Linux
```yaml
paths:
  base_dir: "/Volumes/Photos"

  sources:
    - path: "2024_Birds"
      recursive: true
```

## 3. Restart Application
After editing `settings.yaml`, restart the FeatherTrace web server for changes to take effect:
```bash
python src/web/app.py
```
