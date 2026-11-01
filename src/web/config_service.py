import asyncio
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

from src.utils.settings import first_run_defaults, shape_errors, with_defaults
from src.utils.config_loader import validate_paths_config


def get_config(base_dir: Path, definition_provider):
    config_path = base_dir / "config" / "settings.yaml"
    result = {"config": first_run_defaults(), "definition": definition_provider(),
              "is_first_run": not config_path.exists()}
    if not config_path.exists():
        return result
    try:
        current = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        current = {} if current is None else current
        if shape_errors(current):
            raise ValueError("Invalid configuration shape")
        result["config"] = current
    except (OSError, ValueError, yaml.YAMLError):
        result["error"] = "配置文件格式错误或无法读取，请修复 settings.yaml 后重试；原文件未修改。"
    return result


def save_config(req, base_dir: Path, set_nested_value):
    config_path = base_dir / "config" / "settings.yaml"
    try:
        current = (yaml.safe_load(config_path.read_text(encoding="utf-8"))
                   if config_path.exists() else first_run_defaults())
        current = {} if current is None else current
        if shape_errors(current):
            raise ValueError("Invalid configuration shape")
    except (OSError, ValueError, yaml.YAMLError):
        return {"status": "error", "error": "原配置无法读取或格式错误，请先修复 settings.yaml；原文件未修改。"}

    old_db_path = current.get("paths", {}).get("db_path", "")
    try:
        for item in req.configs:
            value = item.value
            if item.type == "int":
                value = int(value)
            elif item.type == "float":
                value = float(value)
            elif item.type == "bool":
                if value.lower() not in ("true", "yes", "1", "on", "false", "no", "0", "off"):
                    raise ValueError("Invalid boolean")
                value = value.lower() in ("true", "yes", "1", "on")
            set_nested_value(current, f"{item.section}.{item.key}", value)
        current = with_defaults(current)
        valid, errors = validate_paths_config(current)
        if not valid:
            return {"status": "error", "error": "; ".join(errors)}
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return {"status": "error", "error": "配置字段格式错误，请检查路径、端口和数值；原文件未修改。"}

    temporary_path = None
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=config_path.parent,
                                         prefix=".settings-", suffix=".tmp", delete=False) as stream:
            temporary_path = Path(stream.name)
            yaml.safe_dump(current, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, config_path)
    except OSError:
        return {"status": "error", "error": "无法保存配置，请检查目录权限；原文件未修改。"}
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    if (current["paths"].get("db_path") or "") != (old_db_path or ""):
        return {"status": "saved", "restart_required": True, "db_path_changed": True}
    if req.restart:
        return {"status": "saved", "restart_required": True}
    return {"status": "saved"}


def restart_server(base_dir: Path, config: dict, startup_host, startup_port, startup_python: str, logger):
    host = startup_host or config["web"]["host"]
    port = startup_port or config["web"]["port"]

    app_path = str(base_dir / "src" / "web" / "app.py")
    cmd = [startup_python, app_path, "--host", str(host), "--port", str(port)]

    logger.info("Restarting server with command: %s", " ".join(cmd))

    def _delayed_exit():
        time.sleep(3)
        logger.info("Exiting old server process")
        os._exit(0)

    try:
        subprocess.Popen(
            cmd,
            cwd=str(base_dir),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )

        exit_thread = threading.Thread(target=_delayed_exit, daemon=True)
        exit_thread.start()
        return {"status": "restarting", "message": "Server restarting..."}
    except Exception as exc:
        logger.error("Failed to restart server: %s", exc)
        return {"error": str(exc)}


def validate_config_path(path: str, path_type: str = "directory"):
    try:
        p = Path(path)
        exists = p.exists()
        is_dir = p.is_dir() if exists else False
        is_file = p.is_file() if exists else False
        can_write = False
        can_read = False

        if exists:
            try:
                if is_file:
                    with open(p, "rb") as f:
                        f.read(1)
                    can_read = True
                elif is_dir:
                    list(p.iterdir())
                    can_read = True
            except Exception:
                pass

            try:
                probe_dir = p if is_dir else p.parent
                with tempfile.TemporaryFile(dir=probe_dir):
                    pass
                can_write = True
            except Exception:
                pass

        return {
            "exists": exists,
            "is_directory": is_dir,
            "is_file": is_file,
            "can_write": can_write,
            "can_read": can_read,
        }
    except Exception as exc:
        return {"error": str(exc)}


def open_folder_dialog(title: str, initial_dir: str = "") -> str:
    if sys.platform == 'win32':
        from src.web.native_picker import choose_path
        return choose_path('folder', title, initial_dir)
    result = {"path": None, "error": None}

    def _run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder = filedialog.askdirectory(title=title, initialdir=initial_dir or None)
            root.destroy()
            result["path"] = folder
        except Exception as exc:
            result["error"] = str(exc)

    thread = threading.Thread(target=_run_dialog)
    thread.start()
    thread.join()

    if result["error"]:
        raise Exception(result["error"])
    return result["path"]


def open_file_dialog(title: str, initial_file: str = "", file_types: str = "") -> str:
    if sys.platform == 'win32':
        from src.web.native_picker import choose_path
        return choose_path('file', title, initial_file, file_types)
    result = {"path": None, "error": None}

    def _run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)

            filetypes = []
            if file_types:
                for ft in file_types.split("|"):
                    if ft:
                        filetypes.append((ft, f"*.{ft}"))

            file = filedialog.askopenfilename(
                title=title,
                initialfile=initial_file or None,
                filetypes=filetypes if filetypes else [("All Files", "*.*")],
            )
            root.destroy()
            result["path"] = file
        except Exception as exc:
            result["error"] = str(exc)

    thread = threading.Thread(target=_run_dialog)
    thread.start()
    thread.join()

    if result["error"]:
        raise Exception(result["error"])
    return result["path"]


async def browse_folder_api(title: str = "选择文件夹", initial_path: str = ""):
    try:
        folder_path = await asyncio.to_thread(open_folder_dialog, title, initial_path)
        return {"path": folder_path}
    except Exception as exc:
        return {"error": str(exc), "path": None}


async def browse_file_api(title: str = "选择文件", initial_path: str = "", file_types: str = "xlsx|xls"):
    try:
        file_path = await asyncio.to_thread(open_file_dialog, title, initial_path, file_types)
        return {"path": file_path}
    except Exception as exc:
        return {"error": str(exc), "path": None}
