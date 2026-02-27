import yaml
import logging
from pathlib import Path

# 全局配置缓存
_config_cache = None

def validate_paths_config(config: dict) -> tuple[bool, list]:
    """
    验证路径配置：
    1. 检查 base_dir 是否存在
    2. 检查 sources 和 output 是否在 base_dir 内
    3. 不允许绝对路径在 sources 和 output 中（除非在 base_dir 内）

    返回: (is_valid, error_messages)
    """
    errors = []
    paths_conf = config.get('paths', {})

    # 1. 检查 base_dir
    base_dir = paths_conf.get('base_dir', '')
    if not base_dir:
        errors.append("base_dir 未配置")
        return False, errors

    base_path = Path(base_dir)
    if not base_path.exists():
        errors.append(f"base_dir 不存在: {base_dir}")
        return False, errors

    if not base_path.is_dir():
        errors.append(f"base_dir 不是有效目录: {base_dir}")

    # 2. 检查 sources
    sources = paths_conf.get('sources', [])
    if not sources:
        errors.append("sources 未配置")

    for src in sources:
        src_path = src.get('path', '')
        if not src_path:
            continue

        # 解析为绝对路径
        if Path(src_path).is_absolute():
            # 绝对路径必须在 base_dir 内
            abs_src = Path(src_path)
            try:
                abs_src.relative_to(base_path)
            except ValueError:
                errors.append(f"source 路径 {src_path} 不在 base_dir {base_dir} 内")
        # 相对路径将以 base_dir 为基准，已自动满足条件

    # 3. 检查 output
    output = paths_conf.get('output', {})
    output_root = output.get('root_dir', '')
    if output_root:
        if Path(output_root).is_absolute():
            # 绝对路径必须在 base_dir 内
            abs_output = Path(output_root)
            try:
                abs_output.relative_to(base_path)
            except ValueError:
                errors.append(f"output.root_dir {output_root} 不在 base_dir {base_dir} 内")
        # 相对路径将以 base_dir 为基准，已自动满足条件

    # 4. 检查 db_path (允许相对于 base_dir)
    db_path = paths_conf.get('db_path', '')
    if db_path:
        # db_path 可以是绝对路径（在 base_dir 内）或相对路径
        if Path(db_path).is_absolute():
            abs_db = Path(db_path)
            try:
                abs_db.relative_to(base_path)
            except ValueError:
                errors.append(f"db_path {db_path} 不在 base_dir {base_dir} 内")

    is_valid = len(errors) == 0
    return is_valid, errors

def get_config() -> dict:
    """
    Get the application configuration (cached).

    This is a convenience function that calls load_config() and caches the result.
    """
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache

def load_config(settings_path: str = "config/settings.yaml", secrets_path: str = "config/secrets.yaml") -> dict:
    """
    Load settings.yaml and merge with secrets.yaml if it exists.
    """
    # 1. Load Base Settings
    config = {}
    base_path = Path(settings_path)
    if base_path.exists():
        with open(base_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    else:
        logging.warning(f"Settings file not found at {base_path}")

    # 2. Load Secrets
    secret_path = Path(secrets_path)
    if secret_path.exists():
        logging.info(f"Loading secrets from {secret_path}")
        with open(secret_path, 'r', encoding='utf-8') as f:
            secrets = yaml.safe_load(f) or {}
            
        # 3. Merge (Simple recursive merge for 'recognition' section)
        if 'recognition' in secrets and 'recognition' in config:
            rec_sec = secrets['recognition']
            target_rec = config['recognition']
            
            for key in ['api', 'dongniao']:
                if key in rec_sec and key in target_rec:
                    # Update keys inside the sub-dict
                    target_rec[key].update(rec_sec[key])
    
    return config
