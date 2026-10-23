import os
import shutil
import logging
from pathlib import Path
from typing import Generator, Optional, List
from .provider import StorageProvider, FileEntry
from .path_utils import is_within_directory
from src.core.quarantine_paths import QUARANTINE_DIR, is_quarantine

class SecurityViolationError(Exception):
    pass

class LocalProvider(StorageProvider):
    # Common NAS and System directories to ignore
    IGNORED_DIRS = {
        '@Recycle', '#recycle', '#Recycle', # Synology/QNAP
        '$RECYCLE.BIN', 'System Volume Information', # Windows
        '.Trash', '.trash', '.Trashes', # Linux/macOS
        '@eaDir', '.@__thumb', # Metadata folders
        '#snapshot', # Snapshots
        QUARANTINE_DIR,
    }

    def __init__(self, base_dir: str = None):
        """
        base_dir: The base directory that all paths must be under.
                  If None, no restriction (use with caution).
        """
        # 不使用 resolve()，保持原始路径格式 (如 Y:/)
        # 否则 Windows 映射驱动器会被解析为 UNC 路径 \\192.168.31.205\share
        self.base_dir = Path(base_dir) if base_dir else None
        self.strict = False

    def _validate_path(self, path_str: str) -> Path:
        # 不使用 resolve()，避免将 Y:/ 转换为 UNC 路径
        path = Path(path_str)
        if self.base_dir and not is_within_directory(path, self.base_dir):
            raise SecurityViolationError(f"Access denied: {path} is not in base_dir {self.base_dir}.")
        return path

    def list_dir(self, path: str, recursive: bool = False) -> Generator[FileEntry, None, None]:
        if is_quarantine(Path(path)):
            raise SecurityViolationError('Quarantine directories cannot be scanned')
        if self.strict:
            yield from self._list_dir_strict(path, recursive)
            return
        p = self._validate_path(path)
        if not p.exists() or not p.is_dir():
            return

        # Use rglob for recursive, iterdir for non-recursive
        iterator = p.rglob("*") if recursive else p.iterdir()
        
        for item in iterator:
            try:
                if is_quarantine(item):
                    continue
                if self.base_dir and not is_within_directory(item, self.base_dir):
                    continue
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
            except OSError:
                logging.warning(f"Cannot inspect directory entry {item}")
                if item.suffix.lower() in {'.jpg', '.jpeg'}:
                    # Let the observed worker retain the read/stat failure.
                    yield FileEntry(path=str(item.absolute()), name=item.name, is_dir=False)
                continue

    def _list_dir_strict(self, path: str, recursive: bool):
        """Scanning must surface directory failures, including nested failures.

        Do not recurse through directory links: this avoids cycles and aliases.
        A JPEG stat failure is passed to its worker for a persistent observation.
        """
        directory = self._validate_path(path)
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith('.') or entry.name in self.IGNORED_DIRS:
                    continue
                item = Path(entry.path)
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    # Linked directories are outside the supported traversal contract.
                    attributes = getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0)
                    if (entry.is_symlink() or attributes & 0x400) and entry.is_dir():
                        continue
                    if entry.is_symlink() and self.base_dir and not is_within_directory(item, self.base_dir):
                        continue
                    size = 0 if is_dir else entry.stat().st_size
                except OSError:
                    if item.suffix.lower() not in {'.jpg', '.jpeg'}:
                        raise
                    is_dir, size = False, 0
                yield FileEntry(str(item.absolute()), is_dir, size, entry.name)
                if recursive and is_dir:
                    yield from self._list_dir_strict(str(item), True)

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
