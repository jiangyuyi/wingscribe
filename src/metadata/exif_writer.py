import logging
import subprocess
import tempfile
import shutil
import os
from pathlib import Path
from typing import List, Dict, Any

class ExifWriter:
    def __init__(self, exiftool_path: str = "exiftool"):
        """
        exiftool_path: Path to the exiftool executable. 
        Ensure it is in PATH or provide absolute path.
        """
        self.exiftool_path = exiftool_path

    def _resolve_exiftool(self) -> str | None:
        """
        Resolve exiftool executable path.
        Priority:
        1) explicit EXIFTOOL_PATH env var
        2) configured exiftool_path (absolute path or command in PATH)
        3) bundled tools/exiftool.exe under app root
        """
        env_path = os.getenv("EXIFTOOL_PATH", "").strip()
        if env_path:
            p = Path(env_path)
            if p.exists():
                return str(p)
            which_env = shutil.which(env_path)
            if which_env:
                return which_env

        # User-provided path or command name
        cfg_path = self.exiftool_path
        p = Path(cfg_path)
        if p.exists():
            return str(p)
        which_cfg = shutil.which(cfg_path)
        if which_cfg:
            return which_cfg

        # Bundled path in installer layout: {app_root}/tools/exiftool.exe
        app_root = Path(__file__).resolve().parents[2]
        bundled = app_root / "tools" / "exiftool.exe"
        if bundled.exists():
            return str(bundled)

        return None

    def write_metadata(self, image_path: str, tags: Dict[str, Any]):
        """
        Write tags to the image using an argfile to handle character encoding correctly.
        """
        exiftool_cmd = self._resolve_exiftool()
        if not exiftool_cmd:
            logging.warning(
                f"ExifTool not found (configured: '{self.exiftool_path}'). Skipping metadata writing."
            )
            return False

        # Prepare arguments for argfile
        # -charset utf8 is passed to CLI, argfile should be UTF-8.
        # Use -E to allow HTML entities for newlines and special chars
        lines = [
            "-m",
            "-overwrite_original",
            "-charset", "iptc=UTF8",
            "-codedcharacterset=utf8",
            "-E" 
        ]
        
        for tag, value in tags.items():
            if isinstance(value, list):
                # For multi-value tags like Keywords
                for v in value:
                    if v is not None: # Changed from 'if v:' to allow empty strings
                        lines.append(f"-{tag}={v}")
            else:
                if value is not None: # Changed from 'if value:' to allow empty strings
                    # Sanitize: Replace newlines with HTML entity &#xa;
                    # ExifTool with -E will decode this back to a newline
                    safe_value = str(value).replace('\n', '&#xa;')
                    lines.append(f"-{tag}={safe_value}")
        
        # Add the image path to the argfile to avoid CLI encoding issues on Windows
        lines.append(str(image_path))
        
        # Write to temporary argfile (UTF-8)
        # delete=False is required on Windows to allow closing before subprocess reads it
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as tf:
                tf.write('\n'.join(lines))
                arg_file = tf.name
        except Exception as e:
            logging.error(f"Failed to create temporary argfile: {e}")
            return False
            
        try:
            cmd = [
                exiftool_cmd,
                "-charset", "utf8", # Interpret argfile and CLI args as UTF-8
                "-@", arg_file
                # image_path is now IN the argfile
            ]
            
            # Run ExifTool
            # capture_output=True to suppress stdout unless error
            # Use text=False (binary mode) to avoid UnicodeDecodeError in background reader thread
            # if output is not valid UTF-8 (e.g. system locale warning)
            subprocess.run(cmd, check=True, capture_output=True, text=False)
            logging.debug(f"Metadata written to {image_path}")
            return True
            
        except subprocess.CalledProcessError as e:
            # Decode stderr safely
            try:
                err_msg = e.stderr.decode('utf-8') if e.stderr else "No stderr"
            except (UnicodeDecodeError, AttributeError):
                # Fallback to system encoding or ignore
                err_msg = e.stderr.decode('mbcs', errors='replace') if e.stderr and os.name == 'nt' else "Failed to decode stderr"

            logging.error(f"Failed to write metadata: {err_msg}")
            return False
        except Exception as e:
            logging.error(f"ExifTool execution error: {e}")
            return False
        finally:
            # Cleanup temp file
            if os.path.exists(arg_file):
                try:
                    os.remove(arg_file)
                except:
                    pass
