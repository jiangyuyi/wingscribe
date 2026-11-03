"""Typed configuration boundaries and safe first-run defaults."""
from copy import deepcopy
import os
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SourceSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str = ""
    enabled: bool = True
    recursive: bool = True


class OutputSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    root_dir: str = ""


class PathsSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    sources: list[SourceSettings] = Field(default_factory=list)
    output: OutputSettings = Field(default_factory=OutputSettings)
    db_path: str | None = None


class WebSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


class ApplicationSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    paths: PathsSettings = Field(default_factory=PathsSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    processing: dict = Field(default_factory=dict)
    recognition: dict = Field(default_factory=dict)


def shape_errors(config: dict) -> list[str]:
    try:
        ApplicationSettings.model_validate(config)
        return []
    except ValidationError as exc:
        # Never include input values: configuration may contain credentials.
        return [f"{'.'.join(map(str, error['loc']))}: {error['type']}" for error in exc.errors(include_input=False)]


def first_run_defaults() -> dict:
    source = Path(__file__).resolve().parents[2] / "config/settings.example.yaml"
    defaults = yaml.safe_load(source.read_text(encoding="utf-8"))
    defaults["paths"]["sources"] = [{"path": "", "enabled": True, "recursive": True}]
    defaults["paths"]["output"]["root_dir"] = ""
    defaults["web"]["host"] = "127.0.0.1"
    return defaults


def new_user_defaults() -> dict:
    """First-install storage is per user; existing configurations keep legacy defaults."""
    defaults = first_run_defaults()
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
        database = base / 'WingScribe/data/wingscribe.db'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
        database = base / 'wingscribe/data/wingscribe.db'
    defaults['paths']['db_path'] = str(database.absolute())
    return defaults


def with_defaults(config: dict) -> dict:
    errors = shape_errors(config)
    if errors:
        raise ValueError("配置字段格式错误: " + "; ".join(errors))
    from .config_loader import _deep_merge_dict

    result = first_run_defaults()
    _deep_merge_dict(result, deepcopy(config))
    # Normalize validated scalars (e.g. a numeric port saved as a YAML string).
    validated = ApplicationSettings.model_validate(result)
    result["paths"] = validated.paths.model_dump()
    result["web"] = validated.web.model_dump()
    return result
