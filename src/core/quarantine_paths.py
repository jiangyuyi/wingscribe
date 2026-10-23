"""Reserved quarantine paths, shared by scanners and file operations."""
import stat
from pathlib import Path


QUARANTINE_DIR = '.wingscribe-quarantine'


def is_quarantine(path: Path) -> bool:
    return any(part.casefold() == QUARANTINE_DIR for part in path.parts)


def checked_path(root: Path, relative: Path) -> Path:
    """Reject traversal and existing links, including Windows junctions.

    Missing destination components are allowed. Call again immediately before IO.
    This is a local cooperative workflow, not protection against hostile OS users.
    """
    if relative.is_absolute() or relative.drive or '..' in relative.parts:
        raise ValueError('路径必须位于照片来源内')
    candidates = list(reversed(root.parents)) + [root]
    current = root
    for part in relative.parts:
        current = current / part
        candidates.append(current)
    for current in candidates:
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('隔离操作不支持链接或目录联接')
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('路径已超出照片来源')
    return target
