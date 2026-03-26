from src.web import app as web_app
from src.web import config_helpers


def test_app_reexports_config_helpers():
    assert web_app.get_config_definition is config_helpers.get_config_definition
    assert web_app.get_nested_value is config_helpers.get_nested_value
    assert web_app.set_nested_value is config_helpers.set_nested_value


def test_get_nested_value_returns_none_for_non_dict_branch():
    assert config_helpers.get_nested_value({"paths": []}, "paths.output.root_dir") is None


def test_config_definition_uses_expected_chinese_labels():
    definition = config_helpers.get_config_definition()

    assert definition["basic"]["paths"][0]["label"] == "照片基准目录"
    assert definition["basic"]["paths"][0]["description"] == "照片源目录（必填，使用绝对路径）"
    assert definition["basic"]["web"][0]["label"] == "监听地址"
