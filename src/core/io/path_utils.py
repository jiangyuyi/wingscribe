"""Filesystem containment checks shared by providers and scanners."""
from pathlib import Path


def is_within_directory(path: str | Path, directory: str | Path) -> bool:
    """Compare resolved components, including Windows junctions and mapped drives.

    Resolution is only used for validation; callers can keep their original path
    spelling for IO and display. Missing descendants are supported for writes.
    """
    try:
        Path(path).resolve().relative_to(Path(directory).resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False
