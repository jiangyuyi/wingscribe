#!/usr/bin/env python3
"""
WingScribe Environment Initialization Script

This script initializes the WingScribe environment by:
1. Creating necessary directories
2. Initializing the database
3. Checking and fixing configuration files
"""

import os
import sys
from pathlib import Path

import yaml


def _load_settings_with_repair(settings_file: Path, app_root: Path) -> dict:
    """Load settings.yaml and auto-repair common Windows path escaping issues."""
    default_config = {
        "paths": {
            "base_dir": str(app_root).replace("\\", "/"),
            "sources": [{"path": ".", "recursive": True, "enabled": True}],
            "output": {
                "root_dir": "data/processed",
                "structure_template": "{source_structure}/{filename}_{species_cn}_{confidence}",
                "write_back_to_source": False,
            },
            "db_path": "data/db/wingscribe.db",
            "references_path": "data/references",
            "ioc_list_path": "data/references/Multiling IOC 15.1_d.xlsx",
            "model_cache_dir": "data/models",
        },
        "processing": {"device": "auto", "yolo_model": "yolo26n.pt"},
        "recognition": {"mode": "local", "region_filter": "auto"},
        "web": {"host": "0.0.0.0", "port": 8000, "log_level": "info"},
    }

    raw = settings_file.read_text(encoding="utf-8")
    try:
        return yaml.safe_load(raw) or {}
    except Exception:
        fixed_raw = raw.replace("\\", "/")
        try:
            config = yaml.safe_load(fixed_raw) or {}
            settings_file.write_text(fixed_raw, encoding="utf-8")
            print("  Fixed: Normalized Windows path separators in settings.yaml")
            return config
        except Exception:
            print("  Warning: settings.yaml is invalid; regenerated a safe default config.")
            with open(settings_file, "w", encoding="utf-8") as f:
                yaml.dump(default_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            return default_config


def init_app():
    """Initialize application environment"""

    # Get the app root (parent of scripts directory)
    script_dir = Path(__file__).parent.resolve()
    app_root = script_dir.parent.resolve()

    print(f"App root: {app_root}")
    print("Initializing WingScribe environment...")

    # 1. Load config to get base_dir
    settings_file = app_root / "config" / "settings.yaml"
    base_dir = None

    if settings_file.exists():
        config = _load_settings_with_repair(settings_file, app_root)
        base_dir_str = config.get('paths', {}).get('base_dir', '')
        if base_dir_str:
            base_dir = Path(base_dir_str)

    # 2. Create necessary directories
    print("Creating directories...")
    directories = [
        app_root / "data" / "db",
        app_root / "data" / "models",
        app_root / "data" / "processed",
        app_root / "data" / "references",
    ]

    # Add base_dir directories if configured
    if base_dir:
        directories.extend([
            base_dir / "data" / "processed",
        ])

    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            print(f"  OK: {directory}")
        except Exception as e:
            print(f"  Warning: Could not create {directory}: {e}")

    # 3. Check and fix config files
    print("\nChecking configuration files...")

    secrets_file = app_root / "config" / "secrets.yaml"

    config_updated = False

    if settings_file.exists():
        # Read and check settings
        config = _load_settings_with_repair(settings_file, app_root)

        # Fix empty db_path
        if config.get('paths', {}).get('db_path') in ('', None):
            if 'paths' not in config:
                config['paths'] = {}
            config['paths']['db_path'] = 'data/db/wingscribe.db'
            config_updated = True
            print("  Fixed: Set db_path to 'data/db/wingscribe.db'")

        # Fix empty output.root_dir
        if config.get('paths', {}).get('output', {}).get('root_dir') in ('', None):
            if 'paths' not in config:
                config['paths'] = {}
            if 'output' not in config['paths']:
                config['paths']['output'] = {}
            config['paths']['output']['root_dir'] = 'data/processed'
            config_updated = True
            print("  Fixed: Set output.root_dir to 'data/processed'")

        # Write back if updated
        if config_updated:
            with open(settings_file, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            print(f"  Updated: {settings_file.name}")
        else:
            print(f"  OK: {settings_file.name} is valid")
    else:
        print(f"  WARNING: {settings_file.name} not found")
        print("  Please complete the configuration in the web interface.")

    # Check/create secrets file
    if not secrets_file.exists():
        # Create minimal secrets.yaml if it doesn't exist
        secrets_example = app_root / "config" / "secrets.example.yaml"
        if secrets_example.exists():
            import shutil
            shutil.copy(secrets_example, secrets_file)
            print(f"  OK: Created secrets.yaml from example")
        else:
            # Create minimal secrets file
            secrets_file.parent.mkdir(parents=True, exist_ok=True)
            with open(secrets_file, 'w', encoding='utf-8') as f:
                f.write("# WingScribe secrets\nhf_api_key: \"\"\ndongniao_api_key: \"\"\n")
            print(f"  OK: Created minimal secrets.yaml")
    else:
        print(f"  OK: secrets.yaml found")

    # 4. Initialize database
    print("\nInitializing database...")
    try:
        sys.path.insert(0, str(app_root))
        from src.metadata.ioc_manager import IOCManager

        # Determine db_path from settings or use default
        db_path = app_root / "data" / "db" / "wingscribe.db"

        # Create IOCManager to initialize database
        mgr = IOCManager(str(db_path))
        mgr.close()

        print(f"  OK: Database initialized at {db_path}")
    except Exception as e:
        print(f"  ERROR: Database initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n========================================")
    print("Initialization complete!")
    print("========================================")
    return True


if __name__ == "__main__":
    try:
        success = init_app()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
