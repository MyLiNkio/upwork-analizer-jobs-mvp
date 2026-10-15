from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import db_environment


def load_jobs(sample_size: int, seed: int, config: dict[str, Any]) -> list[dict[str, str]]:
    import psycopg
    with psycopg.connect(**db_environment(config), autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SELECT id, description FROM jobs WHERE description IS NOT NULL")
            rows = cursor.fetchall()
    unique: dict[str, dict[str, str]] = {}
    for job_id, description in rows:
        key = str(job_id)
        if key not in unique and str(description).strip():
            unique[key] = {"job_id": key, "description": str(description)}
    jobs = list(unique.values())
    if sample_size < 1: raise ValueError("sample_size must be positive")
    random.Random(seed).shuffle(jobs)
    return jobs[:sample_size]


def _sha(job: dict[str, str]) -> str:
    return hashlib.sha256(job["description"].encode()).hexdigest()


def write_dataset(run_dir: Path, jobs: list[dict[str, str]], config: dict[str, Any]) -> None:
    dataset_dir = run_dir / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    with (dataset_dir / "jobs.jsonl").open("w", encoding="utf-8") as output:
        for job in jobs: output.write(json.dumps(job, ensure_ascii=False) + "\n")
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "job_count": len(jobs),
                "job_ids": [job["job_id"] for job in jobs], "text_sha256": {job["job_id"]: _sha(job) for job in jobs},
                "sampling": config["experiment"]}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def read_dataset(run_dir: Path) -> list[dict[str, str]]:
    path = run_dir / "dataset/jobs.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
