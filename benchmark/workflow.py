from __future__ import annotations

import csv
import json
import random
import uuid
from pathlib import Path
from typing import Any

from .dataset import load_jobs, read_dataset, write_dataset
from .openai_batch import (extraction_body, evaluation_body, parse_output, submit, sync, verify_models, write_requests)
from .schema import EVALUATION_SCHEMA, EXTRACTION_SCHEMA, validate_result


def run_dir(config: dict[str, Any], run_id: str) -> Path:
    return Path(config["storage"]["base_dir"]) / run_id


def prepare(config: dict[str, Any], config_path: str = "config.yaml") -> str:
    verify_models(config["models"])
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    directory = run_dir(config, run_id); directory.mkdir(parents=True)
    (directory / "config.snapshot.yaml").write_text(Path(config_path).read_text(encoding="utf-8"), encoding="utf-8")
    jobs = load_jobs(int(config["experiment"]["sample_size"]), int(config["experiment"]["random_seed"]))
    write_dataset(directory, jobs, config)
    (directory / "prompts").mkdir()
    (directory / "prompts/extraction.txt").write_text("Shared extraction prompt; schema is stored in request bodies.\n", encoding="utf-8")
    return run_id


def _state(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def extract(config: dict[str, Any], run_id: str, model_choice: str = "all", mode: str = "submit") -> None:
    directory = run_dir(config, run_id); jobs = read_dataset(directory)
    roles = {"a": "extractor_a", "b": "extractor_b"} if model_choice == "all" else {model_choice: f"extractor_{model_choice}"}
    for label, role in roles.items():
        root = directory / "extraction" / f"model_{label}"; requests_dir = root / "requests"; root.mkdir(parents=True, exist_ok=True)
        requests = {f"extract_{job['job_id']}": extraction_body(config["models"][role], job, EXTRACTION_SCHEMA, config["processing"].get("reasoning_effort")) for job in jobs}
        request_file = requests_dir / "batch_001.jsonl"; write_requests(request_file, requests)
        state_file = root / "state.json"
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {"requests": list(requests), "status": "prepared"}
        if mode == "dry-run": continue
        if mode in {"submit", "retry-failed"} and "batch_id" not in state:
            state.update(submit(request_file, {"run_id": run_id, "stage": f"extraction_{label}"}, config["processing"].get("completion_window", "24h")))
            _state(state_file, state)
        if mode in {"sync", "resume"} and state.get("batch_id"):
            state = sync(state, root / "responses/results.jsonl", root / "responses/errors.jsonl", int(config["processing"].get("poll_interval_seconds", 30)))
            _state(state_file, state)
            results, errors = parse_output(root / "responses/results.jsonl")
            valid, invalid = {}, dict(errors)
            for custom_id, result in results.items():
                job_id = custom_id.removeprefix("extract_"); problems = validate_result(result, job_id, EXTRACTION_SCHEMA)
                (invalid if problems else valid)[custom_id] = "; ".join(problems) if problems else result
            with (root / "results.jsonl").open("w", encoding="utf-8") as output:
                for custom_id, result in valid.items(): output.write(json.dumps(result, ensure_ascii=False) + "\n")
            (root / "validation.json").write_text(json.dumps({"valid": len(valid), "errors": invalid}, indent=2, ensure_ascii=False), encoding="utf-8")


def evaluate(config: dict[str, Any], run_id: str, mode: str = "submit") -> None:
    directory = run_dir(config, run_id); jobs = {job["job_id"]: job for job in read_dataset(directory)}
    outputs = {}
    for label in ("a", "b"):
        path = directory / "extraction" / f"model_{label}/results.jsonl"
        outputs[label] = {str(row["job_id"]): row for row in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines())} if path.exists() else {}
    pairs = {job_id: (outputs["a"][job_id], outputs["b"][job_id]) for job_id in jobs if job_id in outputs["a"] and job_id in outputs["b"]}
    root = directory / "evaluation"; root.mkdir(parents=True, exist_ok=True)
    requests = {}; mapping = {}
    rng = random.Random(int(config["experiment"]["random_seed"]))
    for index, (job_id, (a, b)) in enumerate(pairs.items()):
        swapped = bool(config["evaluation"].get("swap_positions", True) and rng.randrange(2))
        candidates = (b, a) if swapped else (a, b); custom_id = f"evaluate_{job_id}"
        requests[custom_id] = evaluation_body(config["models"]["evaluator"], jobs[job_id], candidates[0], candidates[1], EVALUATION_SCHEMA, config["processing"].get("reasoning_effort")); mapping[custom_id] = {"job_id": job_id, "swapped": swapped}
    (root / "mapping.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    request_file = root / "requests/batch_001.jsonl"; write_requests(request_file, requests)
    state_file = root / "state.json"; state = json.loads(state_file.read_text()) if state_file.exists() else {"requests": list(requests), "status": "prepared"}
    if mode == "dry-run": return
    if mode == "submit" and "batch_id" not in state:
        state.update(submit(request_file, {"run_id": run_id, "stage": "evaluation"}, config["processing"].get("completion_window", "24h"))); _state(state_file, state)
    if mode in {"sync", "resume"} and state.get("batch_id"):
        state = sync(state, root / "responses/results.jsonl", root / "responses/errors.jsonl", int(config["processing"].get("poll_interval_seconds", 30))); _state(state_file, state)
        results, errors = parse_output(root / "responses/results.jsonl")
        with (root / "results.jsonl").open("w", encoding="utf-8") as output:
            for custom_id, result in results.items():
                if not validate_result(result, mapping[custom_id]["job_id"], EVALUATION_SCHEMA): output.write(json.dumps(result, ensure_ascii=False) + "\n")
        (root / "validation.json").write_text(json.dumps({"errors": errors}, indent=2), encoding="utf-8")
