from pathlib import Path

from src.utils.env_check import check_system_dependencies


def test_check_system_dependencies_creates_missing_directories_and_allows_missing_ioc(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    output_root = tmp_path / "processed"
    db_path = tmp_path / "db" / "wingscribe.db"
    model_dir = tmp_path / "models"

    monkeypatch.setattr("src.utils.env_check.shutil.which", lambda command: "C:/tools/exiftool.exe")

    config = {
        "paths": {
            "sources": [{"path": str(source_root)}],
            "output": {"root_dir": str(output_root)},
            "db_path": str(db_path),
            "model_cache_dir": str(model_dir),
            "ioc_list_path": str(tmp_path / "missing.xlsx"),
        }
    }

    result = check_system_dependencies(config)

    assert result is True
    assert source_root.exists()
    assert output_root.exists()
    assert db_path.parent.exists()
    assert model_dir.exists()


def test_check_system_dependencies_fails_when_exiftool_missing(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    output_root = tmp_path / "processed"

    monkeypatch.setattr("src.utils.env_check.shutil.which", lambda command: None)

    config = {
        "paths": {
            "sources": [{"path": str(source_root)}],
            "output": {"root_dir": str(output_root)},
            "db_path": str(tmp_path / "db" / "wingscribe.db"),
            "model_cache_dir": str(tmp_path / "models"),
        }
    }

    result = check_system_dependencies(config)

    assert result is False
