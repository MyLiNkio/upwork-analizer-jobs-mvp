from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any

from .dataset import load_jobs, read_dataset, write_dataset
from .openai_batch import extraction_body, evaluation_body, parse_output, submit, sync, verify_models, write_requests
from .schema import BATCH_EXTRACTION_SCHEMA, EVALUATION_SCHEMA, validate_extraction_response


def run_dir(config: dict[str, Any], run_id: str) -> Path: return Path(config["storage"]["base_dir"]) / run_id


def prepare(config: dict[str, Any], config_path: str = "config.yaml") -> str:
    verify_models(config["models"]); run_id = f"run_{uuid.uuid4().hex[:12]}"; directory = run_dir(config, run_id); directory.mkdir(parents=True)
    (directory / "config.snapshot.yaml").write_text(Path(config_path).read_text(encoding="utf-8"), encoding="utf-8")
    write_dataset(directory, load_jobs(int(config["experiment"]["sample_size"]), int(config["experiment"]["random_seed"])), config)
    prompt_source = Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.txt"
    (directory / "prompts").mkdir(); (directory / "prompts/system_prompt.txt").write_text(prompt_source.read_text(encoding="utf-8"), encoding="utf-8")
    return run_id


def _state(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp"); temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"); temporary.replace(path)


def request_groups(jobs: list[dict[str, str]], jobs_per_request: int) -> list[list[dict[str, str]]]:
    if jobs_per_request < 1: raise ValueError("jobs_per_request must be >= 1")
    return [jobs[i:i + jobs_per_request] for i in range(0, len(jobs), jobs_per_request)]


def extract(config: dict[str, Any], run_id: str, variant: str = "all", mode: str = "submit") -> None:
    directory = run_dir(config, run_id); jobs = read_dataset(directory)
    selected = list(config.get("variants", {})) if variant == "all" else [variant]
    for variant_id in selected:
        spec = config["variants"][variant_id]; groups = request_groups(jobs, int(spec["jobs_per_request"]))
        root = directory / "extraction" / variant_id; requests_dir = root / "requests"; root.mkdir(parents=True, exist_ok=True)
        requests: dict[str, dict[str, Any]] = {}; mapping: dict[str, Any] = {}
        for index, group in enumerate(groups, 1):
            custom_id = f"{variant_id}_{index:04d}"; requests[custom_id] = extraction_body(spec["model"], group, BATCH_EXTRACTION_SCHEMA, config["processing"].get("reasoning_effort"))
            mapping[custom_id] = {"job_ids": [str(job["job_id"]) for job in group]}
        request_file = requests_dir / "batch_001.jsonl"; write_requests(request_file, requests)
        (root / "request_mapping.json").write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
        state_file = root / "state.json"; state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {"variant_id": variant_id, "requests": list(requests), "status": "prepared", "jobs_per_request": spec["jobs_per_request"]}
        if mode == "dry-run": continue
        if mode in {"submit", "retry-failed"} and "batch_id" not in state:
            state.update(submit(request_file, {"run_id": run_id, "variant_id": variant_id, "stage": "extraction"}, config["processing"].get("completion_window", "24h"))); _state(state_file, state)
        if mode in {"sync", "resume"} and state.get("batch_id"):
            state = sync(state, root / "responses/results.jsonl", root / "responses/errors.jsonl", int(config["processing"].get("poll_interval_seconds", 30))); _state(state_file, state)
            responses, errors = parse_output(root / "responses/results.jsonl"); valid: dict[str, Any] = {}; validation: dict[str, Any] = {"errors": errors, "requests": {}}
            for custom_id, response in responses.items():
                group = next((g for cid, g in zip(mapping, groups) if cid == custom_id), [])
                indexed, problems = validate_extraction_response(response, group)
                validation["requests"][custom_id] = problems
                if not problems:
                    valid.update(indexed)
            with (root / "results.jsonl").open("w", encoding="utf-8") as output:
                for result in valid.values(): output.write(json.dumps(result, ensure_ascii=False) + "\n")
            (root / "validation.json").write_text(json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8")


def evaluate(config: dict[str, Any], run_id: str, mode: str = "submit") -> None:
    directory = run_dir(config, run_id); jobs = {str(j["job_id"]): j for j in read_dataset(directory)}; variants = list(config.get("variants", {}))
    outputs = {v: {str(json.loads(line)["job_id"]): json.loads(line) for line in (directory / "extraction" / v / "results.jsonl").read_text(encoding="utf-8").splitlines()} if (directory / "extraction" / v / "results.jsonl").exists() else {} for v in variants}
    complete = [job_id for job_id in jobs if all(job_id in outputs[v] for v in variants)]
    root = directory / "evaluation"; root.mkdir(parents=True, exist_ok=True); requests: dict[str, Any] = {}; mapping: dict[str, Any] = {}
    rng = random.Random(int(config["experiment"]["random_seed"]))
    for index, job_id in enumerate(complete):
        order = list(variants); rng.shuffle(order); candidates = [outputs[v][job_id] for v in order]; custom_id = f"evaluate_{index:04d}_{job_id}"
        requests[custom_id] = evaluation_body(config["models"]["evaluator"], jobs[job_id], candidates, EVALUATION_SCHEMA, config["processing"].get("reasoning_effort")); mapping[custom_id] = {"job_id": job_id, "order": order}
    (root / "mapping.json").write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8"); request_file = root / "requests/batch_001.jsonl"; write_requests(request_file, requests)
    state_file = root / "state.json"; state = json.loads(state_file.read_text()) if state_file.exists() else {"requests": list(requests), "status": "prepared", "eligible_jobs": complete}
    if mode == "dry-run": return
    if mode == "submit" and "batch_id" not in state: state.update(submit(request_file, {"run_id": run_id, "stage": "evaluation"}, config["processing"].get("completion_window", "24h"))); _state(state_file, state)
    if mode in {"sync", "resume"} and state.get("batch_id"):
        state = sync(state, root / "responses/results.jsonl", root / "responses/errors.jsonl", int(config["processing"].get("poll_interval_seconds", 30))); _state(state_file, state)
        results, errors = parse_output(root / "responses/results.jsonl"); (root / "results.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results.values()) + ("\n" if results else ""), encoding="utf-8"); (root / "validation.json").write_text(json.dumps({"errors": errors}, indent=2), encoding="utf-8")
