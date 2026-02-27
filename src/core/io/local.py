import os
import shutil
import logging
from pathlib import Path
from typing import Generator, Optional, List
from .provider import StorageProvider, FileEntry

class SecurityViolationError(Exception):
    pass

class LocalProvider(StorageProvider):
    # Common NAS and System directories to ignore
    IGNORED_DIRS = {
        '@Recycle', '#recycle', '#Recycle', # Synology/QNAP
        '$RECYCLE.BIN', 'System Volume Information', # Windows
        '.Trash', '.trash', '.Trashes', # Linux/macOS
        '@eaDir', '.@__thumb', # Metadata folders
        '#snapshot' # Snapshots
    }

    def __init__(self, base_dir: str = None):
        """
        base_dir: The base directory that all paths must be under.
                  If None, no restriction (use with caution).
        """
        self.base_dir = Path(base_dir).resolve() if base_dir else None

    def _validate_path(self, path_str: str) -> Path:
        path = Path(path_str).resolve()
        if self.base_dir:
            # 检查路径是否在 base_dir 内
            try:
                path.relative_to(self.base_dir)
            except ValueError:
                raise SecurityViolationError(f"Access denied: {path} is not in base_dir {self.base_dir}.")
        return path

    def list_dir(self, path: str, recursive: bool = False) -> Generator[FileEntry, None, None]:
        p = self._validate_path(path)
        if not p.exists() or not p.is_dir():
            return

        # Use rglob for recursive, iterdir for non-recursive
        iterator = p.rglob("*") if recursive else p.iterdir()
        
        for item in iterator:
            try:
                # Skip hidden files or system dirs if needed
                if item.name.startswith('.'): continue
                
                # Check for ignored directories in path parts
                # If any part of the relative path (from root p) matches an ignored dir, skip it
                try:
                    rel_parts = item.relative_to(p).parts
                    if any(part in self.IGNORED_DIRS for part in rel_parts):
                        continue
                except ValueError:
                    pass # Should not happen usually
                
                yield FileEntry(
                    path=str(item.absolute()),
                    name=item.name,
                    is_dir=item.is_dir(),
                    size=item.stat().st_size if item.is_file() else 0
                )
            except PermissionError:
                logging.warning(f"Permission denied accessing {item}")
                continue

    def exists(self, path: str) -> bool:
        try:
            p = self._validate_path(path)
            return p.exists()
        except SecurityViolationError:
            return False

    def read_bytes(self, path: str) -> bytes:
        p = self._validate_path(path)
        return p.read_bytes()

    def write_bytes(self, path: str, data: bytes):
        p = self._validate_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def delete(self, path: str):
        p = self._validate_path(path)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)

    def move(self, src_path: str, dest_path: str):
        src = self._validate_path(src_path)
        dest = self._validate_path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dest)

    def get_local_path(self, path: str) -> Optional[str]:
        # For local provider, the path is always local
        return str(self._validate_path(path))
