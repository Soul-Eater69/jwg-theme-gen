"""Shared service utilities."""

from __future__ import annotations

from pathlib import Path

import yaml


def load_config(path: str) -> dict:
    """Read the user config from a YAML file (the injected ``user_config_path``)."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
