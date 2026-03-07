import yaml
import logging
from pathlib import Path

# 全局配置缓存
_config_cache = None

def validate_paths_config(config: dict) -> tuple[bool, list]:
    """
    验证路径配置：
    1. 检查 sources.path 是否为必填绝对路径（格式检查，不强制要求目录存在）
    2. 检查 output.root_dir 是否为必填绝对路径（格式检查，不强制要求目录存在）
    3. 检查相对路径引用的目录是否存在（仅警告，不阻止启动）

    返回: (is_valid, error_messages)
    """
    errors = []
    warnings = []
    paths_conf = config.get('paths', {})

    # 1. 检查 sources.path（必填，绝对路径 - 格式检查）
    sources = paths_conf.get('sources', [])
    if not sources:
        errors.append("sources 未配置")
    else:
        src = sources[0]
        src_path = src.get('path', '')
        if not src_path:
            errors.append("sources[0].path 未配置（必填）")
        elif not Path(src_path).is_absolute():
            errors.append(f"sources[0].path 必须是绝对路径: {src_path}")
        elif not Path(src_path).exists():
            warnings.append(f"sources[0].path 目录不存在（将在首次配置时创建）: {src_path}")

    # 2. 检查 output.root_dir（必填，绝对路径 - 格式检查）
    output = paths_conf.get('output', {})
    output_root = output.get('root_dir', '')
    if not output_root:
        errors.append("output.root_dir 未配置（必填）")
    elif not Path(output_root).is_absolute():
        errors.append(f"output.root_dir 必须是绝对路径: {output_root}")
    elif not Path(output_root).exists():
        warnings.append(f"output.root_dir 目录不存在（将在首次配置时创建）: {output_root}")

    # 3. 检查相对路径引用的目录（仅警告，不阻止启动）
    project_root = Path.cwd()

    # references_path
    refs_path = paths_conf.get('references_path', '')
    if refs_path:
        abs_refs = project_root / refs_path
        if not abs_refs.exists():
            warnings.append(f"references_path 目录不存在: {abs_refs}")

    # ioc_list_path
    ioc_path = paths_conf.get('ioc_list_path', '')
    if ioc_path:
        abs_ioc = project_root / ioc_path
        if not abs_ioc.exists():
            warnings.append(f"ioc_list_path 文件不存在: {abs_ioc}")

    # model_cache_dir
    model_dir = paths_conf.get('model_cache_dir', '')
    if model_dir:
        abs_model = project_root / model_dir
        if not abs_model.exists():
            warnings.append(f"model_cache_dir 目录不存在: {abs_model}")

    # 打印警告信息
    for warn in warnings:
        logging.warning(f"配置警告: {warn}")

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
