from src.web import app as web_app
from src.web import config_helpers


def test_app_reexports_config_helpers():
    assert web_app.get_config_definition is config_helpers.get_config_definition
    assert web_app.get_nested_value is config_helpers.get_nested_value
    assert web_app.set_nested_value is config_helpers.set_nested_value


def test_get_nested_value_returns_none_for_non_dict_branch():
    assert config_helpers.get_nested_value({"paths": []}, "paths.output.root_dir") is None
