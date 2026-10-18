import asyncio

import yaml

from src.web import app as web_module


def test_set_nested_value_supports_array_indexes(web_app):
    target = {"paths": {}}

    web_app.set_nested_value(target, "paths.sources[0].path", "D:/photos")
    web_app.set_nested_value(target, "paths.output.root_dir", "D:/processed")

    assert target == {
        "paths": {
            "sources": [{"path": "D:/photos"}],
            "output": {"root_dir": "D:/processed"},
        }
    }


def test_save_config_writes_nested_values_and_type_converts(web_app, tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "BASE_DIR", tmp_path)

    request = web_module.SaveConfigRequest(
        configs=[
            web_module.ConfigItem(section="paths", key="sources[0].path", value="D:/photos"),
            web_module.ConfigItem(section="paths", key="output.root_dir", value="D:/processed"),
            web_module.ConfigItem(section="web", key="port", value="9000", type="int"),
            web_module.ConfigItem(section="processing", key="skip_blurry", value="true", type="bool"),
        ],
        restart=False,
    )

    response = asyncio.run(web_app.save_config(request))

    assert response == {"status": "saved"}

    saved_config = yaml.safe_load((tmp_path / "config" / "settings.yaml").read_text(encoding="utf-8"))
    assert saved_config["paths"]["sources"][0]["path"] == "D:/photos"
    assert saved_config["paths"]["output"]["root_dir"] == "D:/processed"
    assert saved_config["web"]["port"] == 9000
    assert saved_config["processing"]["skip_blurry"] is True


def test_save_config_marks_restart_required_when_db_path_changes(web_app, tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "BASE_DIR", tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yaml").write_text(
        yaml.dump({"paths": {"db_path": "data/db/old.db", "sources": [{"path": str(tmp_path / "source")}], "output": {"root_dir": str(tmp_path / "output")}}}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    request = web_module.SaveConfigRequest(
        configs=[
            web_module.ConfigItem(section="paths", key="db_path", value=str(tmp_path / "data" / "db" / "new.db")),
        ],
        restart=False,
    )

    response = asyncio.run(web_app.save_config(request))

    assert response == {"status": "saved", "restart_required": True, "db_path_changed": True}

    saved_config = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    assert saved_config["paths"]["db_path"] == str(tmp_path / "data" / "db" / "new.db")


def test_failed_atomic_save_preserves_original(web_app, tmp_path, monkeypatch):
    from src.web import config_service
    from src.utils.settings import first_run_defaults
    config = first_run_defaults()
    config["paths"]["sources"][0]["path"] = str(tmp_path / "source")
    config["paths"]["output"]["root_dir"] = str(tmp_path / "output")
    config["custom_extension"] = {"keep": True}
    target = tmp_path / "config/settings.yaml"
    target.parent.mkdir()
    target.write_text(yaml.safe_dump(config), encoding="utf-8")
    original = target.read_bytes()
    monkeypatch.setattr(config_service.os, "replace", lambda *args: (_ for _ in ()).throw(OSError()))
    response = config_service.save_config(web_module.SaveConfigRequest(configs=[], restart=False), tmp_path, web_app.set_nested_value)
    assert response["status"] == "error"
    assert target.read_bytes() == original
    assert list(target.parent.iterdir()) == [target]


def test_invalid_save_does_not_create_config_directory(web_app, tmp_path):
    from src.web import config_service
    request = web_module.SaveConfigRequest(configs=[web_module.ConfigItem(section="web", key="port", value="70000", type="int")])
    assert config_service.save_config(request, tmp_path, web_app.set_nested_value)["status"] == "error"
    assert not (tmp_path / "config").exists()


def test_malformed_yaml_remains_available_for_repair(web_app, tmp_path):
    from src.web import config_service
    target = tmp_path / "config/settings.yaml"
    target.parent.mkdir()
    target.write_text("paths: [", encoding="utf-8")
    result = config_service.get_config(tmp_path, lambda: {"basic": {}})
    assert result["error"]
    assert result["definition"] == {"basic": {}}
    assert config_service.save_config(web_module.SaveConfigRequest(configs=[]), tmp_path, web_app.set_nested_value)["status"] == "error"
    assert target.read_text(encoding="utf-8") == "paths: ["


def test_setup_mode_blocks_processing_without_initializing_database(web_app, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(web_app, "startup_errors", ["Invalid settings"])
    monkeypatch.setattr(web_app, "init_app_db", lambda: (_ for _ in ()).throw(AssertionError("Must not initialize")))
    with TestClient(web_app.app) as client:
        assert client.post("/api/pipeline/start").status_code == 409
        assert client.get("/settings").status_code == 200


def test_path_probe_preserves_existing_named_file(tmp_path):
    from src.web.config_service import validate_config_path
    sentinel = tmp_path / ".wingscribe_write_test"
    sentinel.write_text("keep", encoding="utf-8")
    assert validate_config_path(str(tmp_path))["can_write"]
    assert sentinel.read_text(encoding="utf-8") == "keep"
