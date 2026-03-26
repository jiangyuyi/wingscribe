import shutil
import logging
import sys
from pathlib import Path
from typing import List

def check_system_dependencies(config: dict) -> bool:
    """
    Checks if external dependencies and critical paths exist.
    Returns True if all critical checks pass, False otherwise.
    """
    logging.info("Running system health check...")
    all_good = True

    # 1. Check ExifTool
    if not shutil.which("exiftool"):
        logging.error("CRITICAL: 'exiftool' not found in system PATH.")
        logging.error("Please install ExifTool and ensure it is added to your PATH.")
        logging.error("Download: https://exiftool.org/")
        all_good = False
    else:
        logging.info("✔ ExifTool found.")

    # 2. Check Critical Directories
    # Based on standard structure, but respecting config if provided
    paths = config.get('paths', {})
    source_path = ''
    sources = paths.get('sources', [])
    if sources:
        source_path = sources[0].get('path', '')

    output_root = paths.get('output', {}).get('root_dir', '')

    paths_to_check = [
        source_path or paths.get('raw_dir', 'data/raw'),
        output_root or paths.get('processed_dir', 'data/processed'),
        Path(paths.get('db_path', 'data/db/wingscribe.db')).parent,
        paths.get('model_cache_dir', 'data/models')
    ]

    for p in paths_to_check:
        path_obj = Path(p)
        if not path_obj.exists():
            try:
                path_obj.mkdir(parents=True, exist_ok=True)
                logging.info(f"✔ Created missing directory: {path_obj}")
            except Exception as e:
                logging.error(f"CRITICAL: Could not create directory {path_obj}: {e}")
                all_good = False
        else:
            # logging.debug(f"✔ Directory exists: {path_obj}")
            pass

    # 3. Check Reference Files (Warn only)
    ioc_path = Path(config.get('paths', {}).get('ioc_list_path', ''))
    if not ioc_path.exists():
        logging.warning(f"⚠ IOC List file not found at: {ioc_path}")
        logging.warning("  You may need to run 'scripts/download_ioc.py' or check your paths.")
    
    return all_good
