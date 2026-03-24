import re


def get_config_definition():
    """Return the configuration schema for UI."""
    return {
        "basic": {
            "paths": [
                {
                    "key": "sources[0].path",
                    "label": "鐓х墖鍩哄噯鐩綍",
                    "description": "鐓х墖婧愮洰褰曪紙蹇呭～锛屼娇鐢ㄧ粷瀵硅矾寰勶級",
                    "type": "path",
                    "required": True
                },
                {
                    "key": "output.root_dir",
                    "label": "杈撳嚭鐩綍",
                    "description": "瑁佸垏杈撳嚭鐩綍锛堝繀濉紝浣跨敤缁濆璺緞锛?",
                    "type": "path",
                    "required": True
                }
            ],
            "web": [
                {
                    "key": "host",
                    "label": "鐩戝惉鍦板潃",
                    "description": "0.0.0.0 = 鍏佽灞€鍩熺綉璁块棶锛?27.0.0.1 = 浠呮湰鏈?",
                    "type": "string",
                    "default": "0.0.0.0"
                },
                {
                    "key": "port",
                    "label": "绔彛鍙?",
                    "description": "Web 鏈嶅姟璁块棶绔彛",
                    "type": "int",
                    "default": 8000
                }
            ]
        },
        "advanced": {
            "paths": [
                {
                    "key": "db_path",
                    "label": "鏁版嵁搴撹矾寰?",
                    "description": "SQLite 鏁版嵁搴撴枃浠朵綅缃?",
                    "type": "file"
                },
                {
                    "key": "references_path",
                    "label": "鍙傝€冩暟鎹洰褰?",
                    "description": "IOC 楦熺被鍚嶅綍绛夊弬鑰冩枃浠?",
                    "type": "directory"
                },
                {
                    "key": "ioc_list_path",
                    "label": "IOC 楦熺被鍚嶅綍",
                    "description": "Excel 鏍煎紡鐨勯笩绫诲垎绫绘暟鎹?",
                    "type": "file"
                },
                {
                    "key": "model_cache_dir",
                    "label": "妯″瀷缂撳瓨鐩綍",
                    "description": "BioCLIP 妯″瀷缂撳瓨浣嶇疆",
                    "type": "directory"
                },
                {
                    "key": "output.structure_template",
                    "label": "杈撳嚭璺緞妯℃澘",
                    "description": "澶勭悊鍚庣殑鏂囦欢鍛藉悕妯℃澘",
                    "type": "string",
                    "default": "{source_structure}/{filename}_{species_cn}_{confidence}"
                },
                {
                    "key": "output.write_back_to_source",
                    "label": "鍥炲啓鍘熷浘",
                    "description": "鏄惁灏嗗厓鏁版嵁鍐欏洖鍘熷鐓х墖",
                    "type": "bool",
                    "default": False
                }
            ],
            "processing": [
                {
                    "key": "device",
                    "label": "澶勭悊璁惧",
                    "description": "auto/cuda/cpu",
                    "type": "select",
                    "options": ["auto", "cuda", "cpu"],
                    "default": "auto"
                },
                {
                    "key": "yolo_model",
                    "label": "YOLO 妯″瀷",
                    "description": "楦熺被妫€娴嬫ā鍨?",
                    "type": "string",
                    "default": "yolo26n.pt"
                },
                {
                    "key": "confidence_threshold",
                    "label": "妫€娴嬬疆淇″害",
                    "description": "YOLO 妫€娴嬮槇鍊?(0-1)",
                    "type": "float",
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0
                },
                {
                    "key": "blur_threshold",
                    "label": "妯＄硦闃堝€?",
                    "description": "妯＄硦鐓х墖妫€娴嬮槇鍊?",
                    "type": "float",
                    "default": 40.0
                },
                {
                    "key": "target_size",
                    "label": "鐩爣灏哄",
                    "description": "鍥惧儚澶勭悊鐩爣灏哄",
                    "type": "int",
                    "default": 640
                },
                {
                    "key": "crop_padding",
                    "label": "瑁佸壀杈硅窛",
                    "description": "楦熺被瑁佸壀鍖哄煙鐨勬墿灞曡竟璺?",
                    "type": "int",
                    "default": 200
                }
            ],
            "recognition": [
                {
                    "key": "mode",
                    "label": "璇嗗埆妯″紡",
                    "description": "local/api/dongniao",
                    "type": "select",
                    "options": ["local", "api", "dongniao"],
                    "default": "local"
                },
                {
                    "key": "region_filter",
                    "label": "鍖哄煙杩囨护",
                    "description": "china/auto/null",
                    "type": "select",
                    "options": ["china", "auto", "null"],
                    "default": "auto"
                },
                {
                    "key": "top_k",
                    "label": "Top-K 鍊欓€?",
                    "description": "杩斿洖鍓?K 涓€欓€夌墿绉?",
                    "type": "int",
                    "default": 5
                },
                {
                    "key": "alternatives_threshold",
                    "label": "澶囬€夐槇鍊?",
                    "description": "鏄剧ず澶囬€夌粨鏋滅殑缃俊搴﹂槇鍊?",
                    "type": "int",
                    "default": 70
                },
                {
                    "key": "low_confidence_threshold",
                    "label": "浣庣疆淇″害闃堝€?",
                    "description": "鏍囪涓轰笉纭畾鐨勭疆淇″害闃堝€?",
                    "type": "int",
                    "default": 60
                }
            ],
            "web": [
                {
                    "key": "log_level",
                    "label": "鏃ュ織绾у埆",
                    "description": "info/debug",
                    "type": "select",
                    "options": ["info", "debug"],
                    "default": "info"
                }
            ]
        }
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
