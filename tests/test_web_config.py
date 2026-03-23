import asyncio

import yaml

from src.web import app as web_app


def test_set_nested_value_supports_array_indexes():
    target = {"paths": {}}

    web_app.set_nested_value(target, "paths.sources[0].path", "D:/photos")
    web_app.set_nested_value(target, "paths.output.root_dir", "D:/processed")

    assert target == {
        "paths": {
            "sources": [{"path": "D:/photos"}],
            "output": {"root_dir": "D:/processed"},
        }
    }


def test_save_config_writes_nested_values_and_type_converts(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "BASE_DIR", tmp_path)

    request = web_app.SaveConfigRequest(
        configs=[
            web_app.ConfigItem(section="paths", key="sources[0].path", value="D:/photos"),
            web_app.ConfigItem(section="paths", key="output.root_dir", value="D:/processed"),
            web_app.ConfigItem(section="web", key="port", value="9000", type="int"),
            web_app.ConfigItem(section="processing", key="skip_blurry", value="true", type="bool"),
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


def test_save_config_marks_restart_required_when_db_path_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "BASE_DIR", tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yaml").write_text(
        yaml.dump({"paths": {"db_path": "data/db/old.db"}}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    request = web_app.SaveConfigRequest(
        configs=[
            web_app.ConfigItem(section="paths", key="db_path", value=str(tmp_path / "data" / "db" / "new.db")),
        ],
        restart=False,
    )

    response = asyncio.run(web_app.save_config(request))

    assert response == {"status": "saved", "restart_required": True, "db_path_changed": True}

    saved_config = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    assert saved_config["paths"]["db_path"] == str(tmp_path / "data" / "db" / "new.db")
