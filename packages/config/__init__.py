"""Shared config loading: YAML file + environment variable expansion."""

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel

from packages.config.dotenv import load_dotenv
from packages.config.env import MissingEnvVar, expand_env

__all__ = [
    "CONFIG_DIR",
    "MissingEnvVar",
    "expand_env",
    "load_dotenv",
    "load_yaml_config",
]

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load_yaml_config[ConfigT: BaseModel](
    path: Path,
    model: type[ConfigT],
    environ: Mapping[str, str] | None = None,
) -> ConfigT:
    """Read a YAML file, expand env placeholders, validate into ``model``."""
    expanded = expand_env(path.read_text(encoding="utf-8"), environ)
    data = yaml.safe_load(expanded)
    return model.model_validate(data)
