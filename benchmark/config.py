from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    return value


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        config = _expand(yaml.safe_load(stream) or {})
    required = ("extractor_a", "extractor_b", "evaluator")
    missing = [name for name in required if not config.get("models", {}).get(name) or str(config["models"][name]).startswith("${")]
    if missing:
        raise ValueError(f"Missing configured model IDs: {', '.join(missing)}")
    return config


def db_environment() -> dict[str, Any]:
    keys = {"host": "DB_HOST", "port": "DB_PORT", "database": "DB_NAME", "user": "DB_USER", "password": "DB_PASSWORD"}
    result = {field: os.environ.get(variable) for field, variable in keys.items()}
    result["port"] = int(result["port"] or 5432)
    missing = [key for key, value in result.items() if value in (None, "")]
    if missing: raise ValueError(f"Missing database environment variables: {', '.join(missing)}")
    return result
