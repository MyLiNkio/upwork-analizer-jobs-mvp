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
    models = config.setdefault("models", {})
    variants = config.get("variants", {})
    models.setdefault("extractor_a", variants.get("v1", {}).get("model"))
    models.setdefault("extractor_b", variants.get("v3", {}).get("model"))
    models.setdefault("evaluator", config.get("evaluation", {}).get("model"))
    required = ("extractor_a", "extractor_b", "evaluator")
    missing = [name for name in required if not models.get(name) or str(models[name]).startswith("${")]
    if missing:
        raise ValueError(f"Missing configured model IDs: {', '.join(missing)}")
    # Keep old configurations usable while exposing the four-variant model.
    variants = config.setdefault("variants", {})
    defaults = {"v1": ("extractor_a", 1), "v2": ("extractor_a", 100), "v3": ("extractor_b", 1), "v4": ("extractor_b", 100)}
    for variant, (role, size) in defaults.items():
        item = variants.setdefault(variant, {})
        item.setdefault("model", config["models"][role]); item.setdefault("jobs_per_request", size)
        if int(item["jobs_per_request"]) < 1: raise ValueError(f"{variant}.jobs_per_request must be >= 1")
    config.setdefault("evaluation", {}).setdefault("compare_all_variants", True)
    return config


def db_environment() -> dict[str, Any]:
    keys = {"host": "DB_HOST", "port": "DB_PORT", "database": "DB_NAME", "user": "DB_USER", "password": "DB_PASSWORD"}
    result = {field: os.environ.get(variable) for field, variable in keys.items()}
    result["port"] = int(result["port"] or 5432)
    missing = [key for key, value in result.items() if value in (None, "")]
    if missing: raise ValueError(f"Missing database environment variables: {', '.join(missing)}")
    return result
