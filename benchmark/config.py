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
    # Model IDs are fixed by the experiment; only OPENAI_API_KEY is read from
    # the environment (the OpenAI SDK reads it automatically).
    models = config.setdefault("models", {})
    models["extractor_a"] = "gpt-5.6-luna"
    models["extractor_b"] = "gpt-6-luna"
    models["evaluator"] = "gpt-5.6-sol"
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


def db_environment(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return read-only database connection settings from config.yaml."""
    if not config or not config.get("database"):
        raise ValueError("Database settings are required under the database section of config.yaml")
    database = config["database"]
    required = ("host", "port", "name", "user", "password")
    missing = [key for key in required if database.get(key) in (None, "")]
    if missing: raise ValueError(f"Missing database configuration: {', '.join(missing)}")
    return {"host": database["host"], "port": int(database["port"]), "dbname": database["name"], "user": database["user"], "password": database["password"]}
