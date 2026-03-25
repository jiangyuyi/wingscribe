import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import FileResponse

from src.metadata.ioc_manager import IOCManager


def is_absolute_path(p: str) -> bool:
    """Check if path is absolute, including Windows drive-letter and UNC formats."""
    if not p:
        return False
    if p.startswith("/"):
        return True
    if len(p) >= 2 and p[1] == ":":
        return True
    if p.startswith("//") or p.startswith("\\\\"):
        return True
    return False


def create_db_manager(db_path: Path, source_dir: Optional[Path], processed_dir: Optional[Path]) -> IOCManager:
    return IOCManager(
        str(db_path),
        source_base_dir=str(source_dir) if source_dir else "",
        processed_base_dir=str(processed_dir) if processed_dir else "",
    )


def get_db_conn(db_path: Path):
    conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_web_path(original_path_str: str, source_dir: Optional[Path], logger) -> Optional[str]:
    """Resolve raw file path to /static/... URL."""
    if not original_path_str:
        logger.warning("resolve_web_path: empty path")
        return None
    try:
        normalized = original_path_str.replace("\\", "/")
        if source_dir and not is_absolute_path(normalized):
            abs_path = source_dir / normalized
        else:
            abs_path = Path(normalized)

        norm_abs = os.path.normpath(str(abs_path))
        norm_base = os.path.normpath(str(source_dir)) if source_dir else None

        logger.debug(
            "resolve_web_path: input='%s', normalized='%s', abs_path='%s', norm_base=%s",
            original_path_str,
            normalized,
            abs_path,
            norm_base,
        )

        if norm_base and norm_abs.startswith(norm_base):
            rel_part = norm_abs[len(norm_base):].lstrip("/\\")
            result = f"/static/{rel_part.replace(os.sep, '/')}"
            logger.debug("resolve_web_path: rel_part=%s, result=%s", rel_part, result)
            return result

        logger.warning("resolve_web_path: path '%s' is not under source_dir %s", abs_path, source_dir)
    except Exception as exc:
        logger.warning("resolve_web_path failed for '%s': %s", original_path_str, exc)
    return None


def get_processed_file_response(path: str, processed_dir: Optional[Path]):
    full_path = processed_dir / path.replace("/", os.sep) if processed_dir else None
    if full_path and full_path.exists() and full_path.is_file():
        return FileResponse(full_path)
    raise HTTPException(status_code=404, detail=f"File not found: {path}")


def resolve_processed_web_path(
    file_path_str: str,
    processed_dir: Optional[Path],
    base_dir: Path,
    logger,
) -> Optional[str]:
    """Resolve processed file path to /processed/... URL."""
    if not file_path_str:
        return None
    try:
        normalized = file_path_str.replace("\\", "/")

        if processed_dir and not is_absolute_path(normalized):
            abs_path = processed_dir / normalized
        elif not is_absolute_path(normalized):
            abs_path = base_dir / normalized
        else:
            abs_path = Path(normalized)

        norm_abs = os.path.normpath(str(abs_path))
        norm_base = os.path.normpath(str(processed_dir)) if processed_dir else None

        if norm_base and norm_abs.startswith(norm_base):
            rel_part = norm_abs[len(norm_base):].lstrip("/\\")
            return f"/processed/{rel_part.replace(os.sep, '/')}"

        logger.warning(
            "resolve_processed_web_path: path '%s' is not under processed_dir %s",
            abs_path,
            processed_dir,
        )
        return None
    except Exception as exc:
        logger.warning("Failed to resolve processed path '%s': %s", file_path_str, exc)
        return None
