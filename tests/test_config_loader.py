from pathlib import Path

from src.utils.config_loader import load_config, validate_paths_config


def test_load_config_merges_cloud_secrets(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    secrets_path = tmp_path / "secrets.yaml"

    settings_path.write_text(
        """
paths:
  output:
    root_dir: "D:/Processed"
recognition:
  mode: local
cloud:
  huggingface:
    model_id: imageomics/bioclip
""".strip(),
        encoding="utf-8",
    )

    secrets_path.write_text(
        """
cloud:
  huggingface:
    api_token: secret-token
  modelscope:
    api_token: ms-token
recognition:
  dongniao:
    key: dn-key
""".strip(),
        encoding="utf-8",
    )

    config = load_config(str(settings_path), str(secrets_path))

    assert config["cloud"]["huggingface"]["model_id"] == "imageomics/bioclip"
    assert config["cloud"]["huggingface"]["api_token"] == "secret-token"
    assert config["cloud"]["modelscope"]["api_token"] == "ms-token"
    assert config["recognition"]["dongniao"]["key"] == "dn-key"


def test_validate_paths_config_rejects_non_absolute_required_paths():
    is_valid, errors = validate_paths_config(
        {
            "paths": {
                "sources": [{"path": "relative/source"}],
                "output": {"root_dir": "relative/output"},
            }
        }
    )

    assert is_valid is False
    assert any("sources[0].path" in error for error in errors)
    assert any("output.root_dir" in error for error in errors)


def test_validate_paths_config_allows_missing_directories_if_paths_are_absolute(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"

    monkeypatch.chdir(tmp_path)

    is_valid, errors = validate_paths_config(
        {
            "paths": {
                "sources": [{"path": str(source_root)}],
                "output": {"root_dir": str(output_root)},
                "references_path": "refs",
                "ioc_list_path": "refs/ioc.xlsx",
                "model_cache_dir": "models",
            }
        }
    )

    assert is_valid is True
    assert errors == []
