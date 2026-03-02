import logging
import subprocess
import tempfile
import shutil
import os
from typing import List, Dict, Any

class ExifWriter:
    def __init__(self, exiftool_path: str = "exiftool"):
        """
        exiftool_path: Path to the exiftool executable. 
        Ensure it is in PATH or provide absolute path.
        """
        self.exiftool_path = exiftool_path

    def write_metadata(self, image_path: str, tags: Dict[str, Any]):
        """
        Write tags to the image using an argfile to handle character encoding correctly.
        """
        if not shutil.which(self.exiftool_path):
            logging.warning(f"ExifTool not found at '{self.exiftool_path}'. Skipping metadata writing.")
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
                self.exiftool_path,
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