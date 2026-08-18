import re


def get_config_definition():
    """Return the configuration schema for UI."""
    return {
        "basic": {
            "paths": [
                {
                    "key": "sources[0].path",
                    "label": "照片基准目录",
                    "description": "照片源目录（必填，使用绝对路径）",
                    "type": "path",
                    "required": True,
                },
                {
                    "key": "output.root_dir",
                    "label": "输出目录",
                    "description": "裁切输出目录（必填，使用绝对路径）",
                    "type": "path",
                    "required": True,
                },
            ],
            "web": [
                {
                    "key": "host",
                    "label": "监听地址",
                    "description": "0.0.0.0 = 允许局域网访问，127.0.0.1 = 仅本机",
                    "type": "string",
                    "default": "0.0.0.0",
                },
                {
                    "key": "port",
                    "label": "端口号",
                    "description": "Web 服务访问端口",
                    "type": "int",
                    "default": 8000,
                },
            ],
        },
        "advanced": {
            "paths": [
                {
                    "key": "db_path",
                    "label": "数据库路径",
                    "description": "SQLite 数据库文件位置",
                    "type": "file",
                },
                {
                    "key": "references_path",
                    "label": "参考数据目录",
                    "description": "IOC 鸟类名录等参考文件",
                    "type": "directory",
                },
                {
                    "key": "ioc_list_path",
                    "label": "IOC 鸟类名录",
                    "description": "Excel 格式的鸟类分类数据",
                    "type": "file",
                },
                {
                    "key": "model_cache_dir",
                    "label": "模型缓存目录",
                    "description": "BioCLIP 模型缓存位置",
                    "type": "directory",
                },
                {
                    "key": "output.structure_template",
                    "label": "输出路径模板",
                    "description": "处理后的文件命名模板",
                    "type": "string",
                    "default": "{source_structure}/{filename}_{species_cn}_{confidence}",
                },
                {
                    "key": "output.write_back_to_source",
                    "label": "回写原图",
                    "description": "是否将元数据写回原始照片",
                    "type": "bool",
                    "default": False,
                },
            ],
            "processing": [
                {
                    "key": "device",
                    "label": "处理设备",
                    "description": "auto/cuda/cpu",
                    "type": "select",
                    "options": ["auto", "cuda", "cpu"],
                    "default": "auto",
                },
                {
                    "key": "yolo_model",
                    "label": "YOLO 模型",
                    "description": "鸟类检测模型",
                    "type": "string",
                    "default": "yolo26n.pt",
                },
                {
                    "key": "confidence_threshold",
                    "label": "检测置信度",
                    "description": "YOLO 检测阈值(0-1)",
                    "type": "float",
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                },
                {
                    "key": "blur_threshold",
                    "label": "模糊阈值",
                    "description": "legacy_reject 模式下低于此值的照片会被跳过",
                    "type": "float",
                    "default": 40.0,
                },
                {
                    "key": "quality_mode",
                    "label": "质量处理模式",
                    "description": "兼容过滤、仅记录质量分或完全关闭质量计算",
                    "type": "select",
                    "options": ["legacy_reject", "score_only", "disabled"],
                    "default": "legacy_reject",
                },
                {
                    "key": "target_size",
                    "label": "目标尺寸",
                    "description": "图像处理目标尺寸",
                    "type": "int",
                    "default": 640,
                },
                {
                    "key": "crop_padding",
                    "label": "裁切边距",
                    "description": "鸟类裁切区域的扩展边距",
                    "type": "int",
                    "default": 200,
                },
            ],
            "recognition": [
                {
                    "key": "mode",
                    "label": "识别模式",
                    "description": "local/api/dongniao",
                    "type": "select",
                    "options": ["local", "api", "dongniao"],
                    "default": "local",
                },
                {
                    "key": "region_filter",
                    "label": "区域过滤",
                    "description": "china/auto/null",
                    "type": "select",
                    "options": ["china", "auto", "null"],
                    "default": "auto",
                },
                {
                    "key": "top_k",
                    "label": "Top-K 候选",
                    "description": "返回前 K 个候选物种",
                    "type": "int",
                    "default": 5,
                },
                {
                    "key": "alternatives_threshold",
                    "label": "备选阈值",
                    "description": "显示备选结果的置信度阈值",
                    "type": "int",
                    "default": 70,
                },
                {
                    "key": "low_confidence_threshold",
                    "label": "低置信度阈值",
                    "description": "标记为不确定的置信度阈值",
                    "type": "int",
                    "default": 60,
                },
            ],
            "web": [
                {
                    "key": "log_level",
                    "label": "日志级别",
                    "description": "info/debug",
                    "type": "select",
                    "options": ["info", "debug"],
                    "default": "info",
                },
            ],
        },
    }


def get_nested_value(obj, key_path):
    """Get value from nested dict using dot notation."""
    keys = key_path.split(".")
    value = obj
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def set_nested_value(obj, key_path, value):
    """Set value in nested dict using dot notation, supports array indices like sources[0].path."""
    keys = re.split(r"\.(?!\d)", key_path)
    current = obj

    for key in keys[:-1]:
        array_match = re.match(r"^(\w+)\[(\d+)\]$", key)
        if array_match:
            array_key = array_match.group(1)
            index = int(array_match.group(2))

            if array_key not in current:
                current[array_key] = []
            while len(current[array_key]) <= index:
                current[array_key].append({})
            current = current[array_key][index]
        else:
            if key not in current:
                current[key] = {}
            current = current[key]

    final_key = keys[-1]
    array_match = re.match(r"^(\w+)\[(\d+)\]$", final_key)
    if array_match:
        array_key = array_match.group(1)
        index = int(array_match.group(2))
        if array_key not in current:
            current[array_key] = []
        while len(current[array_key]) <= index:
            current[array_key].append({})
        current[array_key][index] = value
    else:
        current[final_key] = value
