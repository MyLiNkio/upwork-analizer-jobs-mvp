from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any

from .dataset import load_jobs, read_dataset, write_dataset
from .openai_batch import extraction_body, evaluation_body, parse_output, submit, sync, usage_from_output, verify_models, write_requests
from .schema import BATCH_EXTRACTION_SCHEMA, validate_extraction_response


def run_dir(config: dict[str, Any], run_id: str) -> Path: return Path(config["storage"]["base_dir"]) / run_id


def prepare(config: dict[str, Any], config_path: str = "config.yaml") -> str:
    verify_models(config["models"]); run_id = f"run_{uuid.uuid4().hex[:12]}"; directory = run_dir(config, run_id); directory.mkdir(parents=True)
    (directory / "config.snapshot.yaml").write_text(Path(config_path).read_text(encoding="utf-8"), encoding="utf-8")
    write_dataset(directory, load_jobs(int(config["experiment"]["sample_size"]), int(config["experiment"]["random_seed"]), config), config)
    prompt_source = Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.txt"
    evaluation_prompt_source = Path(__file__).resolve().parent.parent / "prompts" / "evaluation_prompt.txt"
    (directory / "prompts").mkdir()
    (directory / "prompts/system_prompt.txt").write_text(prompt_source.read_text(encoding="utf-8"), encoding="utf-8")
    (directory / "prompts/evaluation_prompt.txt").write_text(evaluation_prompt_source.read_text(encoding="utf-8"), encoding="utf-8")
    return run_id


def _state(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp"); temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"); temporary.replace(path)


def request_groups(jobs: list[dict[str, str]], jobs_per_request: int) -> list[list[dict[str, str]]]:
    if jobs_per_request < 1: raise ValueError("jobs_per_request must be >= 1")
    return [jobs[i:i + jobs_per_request] for i in range(0, len(jobs), jobs_per_request)]


def _build_evaluation_requests(
    config: dict[str, Any],
    jobs: dict[str, dict[str, str]],
    outputs: dict[str, dict[str, Any]],
    variants: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    variants = variants or list(config.get("variants", {}))
    if len(variants) < 2 or len(variants) > 4:
        raise ValueError(f"Evaluation requires between two and four available variants, got {len(variants)}")
    complete = [job_id for job_id in jobs if all(job_id in outputs[v] for v in variants)]
    if not complete:
        valid_counts = ", ".join(f"{variant}: {len(outputs[variant])}/{len(jobs)}" for variant in variants)
        raise ValueError(
            "No jobs are eligible for evaluation: each job needs a valid extraction result "
            f"from all selected variants ({', '.join(variants)}). Valid results by variant: {valid_counts}. "
            "Check each extraction/<variant>/validation.json for rejected outputs."
        )
    requests: dict[str, Any] = {}
    mapping: dict[str, Any] = {}
    rng = random.Random(int(config["experiment"]["random_seed"]))
    for index, job_id in enumerate(complete):
        order = list(variants)
        rng.shuffle(order)
        custom_id = f"evaluate_{index:04d}_{job_id}"
        candidates: list[dict[str, Any]] = []
        candidate_variants: dict[str, str] = {}
        for candidate_index, variant in enumerate(order, 1):
            candidate_id = f"candidate_{candidate_index}"
            result = outputs[variant][job_id]
            if str(result.get("job_id")) != job_id:
                raise ValueError(f"Extraction result job_id mismatch for variant {variant}: expected {job_id}, got {result.get('job_id')!r}")
            normalized_result = {
                key: result[key]
                for key in ("job_id", "original_text", "normalized_text", "technologies")
            }
            candidates.append({"candidate_id": candidate_id, "normalized_result": normalized_result})
            candidate_variants[candidate_id] = variant
        requests[custom_id] = evaluation_body(
            config["models"]["evaluator"], jobs[job_id], candidates,
            reasoning=config["processing"].get("reasoning_effort"),
        )
        mapping[custom_id] = {"job_id": job_id, "candidate_variants": candidate_variants}
    return requests, mapping, complete


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
        if mode in {"sync", "resume", "revalidate"} and (state.get("batch_id") or mode == "revalidate"):
            if mode != "revalidate":
                state = sync(state, root / "responses/results.jsonl", root / "responses/errors.jsonl", int(config["processing"].get("poll_interval_seconds", 30))); _state(state_file, state)
            responses, errors = parse_output(root / "responses/results.jsonl"); valid: dict[str, Any] = {}; validation: dict[str, Any] = {"errors": errors, "requests": {}}
            usage = usage_from_output(root / "responses/results.jsonl")
            usage.update({"jobs": len(jobs), "average_input_tokens_per_job": usage["input_tokens"] / len(jobs) if jobs else 0, "average_output_tokens_per_job": usage["output_tokens"] / len(jobs) if jobs else 0, "average_total_tokens_per_job": usage["total_tokens"] / len(jobs) if jobs else 0})
            (root / "token_usage.json").write_text(json.dumps(usage, indent=2), encoding="utf-8")
            for custom_id, response in responses.items():
                group = next((g for cid, g in zip(mapping, groups) if cid == custom_id), [])
                # Older extraction batches returned original_title. It was removed
                # from the current result contract, so discard it when revalidating
                # those saved responses and never persist it in results.jsonl.
                if isinstance(response, dict) and isinstance(response.get("jobs"), list):
                    response = {
                        **response,
                        "jobs": [
                            {key: value for key, value in item.items() if key != "original_title"}
                            if isinstance(item, dict) else item
                            for item in response["jobs"]
                        ],
                    }
                indexed, problems = validate_extraction_response(response, group)
                validation["requests"][custom_id] = problems
                valid.update(indexed)
            with (root / "results.jsonl").open("w", encoding="utf-8") as output:
                for result in valid.values(): output.write(json.dumps(result, ensure_ascii=False) + "\n")
            (root / "validation.json").write_text(json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8")


def evaluate(config: dict[str, Any], run_id: str, mode: str = "submit") -> None:
    directory = run_dir(config, run_id)
    jobs: dict[str, dict[str, str]] = {}
    for job in read_dataset(directory):
        job_id = str(job["job_id"])
        if job_id in jobs:
            raise ValueError(f"Duplicate job_id {job_id!r} in run dataset")
        jobs[job_id] = job
    variants = list(config.get("variants", {}))
    outputs: dict[str, dict[str, Any]] = {}
    for variant in variants:
        result_path = directory / "extraction" / variant / "results.jsonl"
        variant_outputs: dict[str, Any] = {}
        if result_path.exists():
            for line_number, line in enumerate(result_path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                result = json.loads(line)
                if not isinstance(result, dict):
                    raise ValueError(f"Expected an object in {result_path} at line {line_number}")
                result_job_id = str(result.get("job_id", ""))
                if result_job_id not in jobs:
                    raise ValueError(f"Unknown job_id {result_job_id!r} in {result_path} at line {line_number}")
                if result_job_id in variant_outputs:
                    raise ValueError(f"Duplicate job_id {result_job_id!r} in {result_path}")
                variant_outputs[result_job_id] = result
        outputs[variant] = variant_outputs
    available_variants = [
        variant for variant in variants
        if outputs[variant]
        and (directory / "extraction" / variant / "state.json").exists()
        and json.loads((directory / "extraction" / variant / "state.json").read_text(encoding="utf-8")).get("status") == "completed"
    ]
    if len(available_variants) < 2:
        counts = ", ".join(f"{variant}: {len(outputs[variant])}/{len(jobs)}" for variant in variants)
        raise ValueError(f"Evaluation requires at least two completed variants with valid outputs. Available: {counts}")
    requests, mapping, complete = _build_evaluation_requests(config, jobs, outputs, available_variants)
    root = directory / "evaluation"; root.mkdir(parents=True, exist_ok=True)
    (root / "mapping.json").write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8"); request_file = root / "requests/batch_001.jsonl"; write_requests(request_file, requests)
    state_file = root / "state.json"; state = json.loads(state_file.read_text()) if state_file.exists() else {"requests": list(requests), "status": "prepared", "eligible_jobs": complete}
    if mode == "dry-run": return
    if mode == "retry-failed":
        retry_state_file = root / "retry_state.json"
        retry_state = json.loads(retry_state_file.read_text(encoding="utf-8")) if retry_state_file.exists() else {}
        if retry_state.get("batch_id"):
            raise ValueError("An evaluation retry batch already exists; use --mode sync to collect it before retrying again")
        error_path = root / "responses/errors.jsonl"
        failed_ids: set[str] = set()
        if error_path.exists():
            for line in error_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    failed_ids.add(str(json.loads(line).get("custom_id", "")))
        output_path = root / "responses/results.jsonl"
        if output_path.exists():
            for line in output_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    failed_ids.discard(str(json.loads(line).get("custom_id", "")))
        source_requests = request_file.read_text(encoding="utf-8").splitlines()
        retry_lines = [line for line in source_requests if json.loads(line).get("custom_id") in failed_ids]
        if not retry_lines:
            raise ValueError("No failed evaluation requests are available to retry")
        retry_request_file = root / "requests/retry_001.jsonl"
        retry_request_file.parent.mkdir(parents=True, exist_ok=True)
        retry_request_file.write_text("\n".join(retry_lines) + "\n", encoding="utf-8")
        retry_state = {
            "requests": [json.loads(line)["custom_id"] for line in retry_lines],
            "status": "prepared",
            "eligible_jobs": [mapping[cid]["job_id"] for cid in (json.loads(line)["custom_id"] for line in retry_lines)],
        }
        retry_state.update(submit(retry_request_file, {"run_id": run_id, "stage": "evaluation-retry"}, config["processing"].get("completion_window", "24h")))
        _state(retry_state_file, retry_state)
        return
    if mode == "submit" and "batch_id" not in state: state.update(submit(request_file, {"run_id": run_id, "stage": "evaluation"}, config["processing"].get("completion_window", "24h"))); _state(state_file, state)
    if mode in {"sync", "resume"} and state.get("batch_id"):
        original_output = root / "responses/results.jsonl"
        original_errors = root / "responses/errors.jsonl"
        if state.get("status") != "completed" or not original_output.exists():
            state = sync(state, original_output, original_errors, int(config["processing"].get("poll_interval_seconds", 30))); _state(state_file, state)
        retry_state_file = root / "retry_state.json"
        if retry_state_file.exists():
            retry_state = json.loads(retry_state_file.read_text(encoding="utf-8"))
            if retry_state.get("batch_id"):
                retry_output = root / "responses/retry_results.jsonl"
                retry_errors = root / "responses/retry_errors.jsonl"
                if retry_state.get("status") != "completed" or not retry_output.exists():
                    retry_state = sync(retry_state, retry_output, retry_errors, int(config["processing"].get("poll_interval_seconds", 30)))
                    _state(retry_state_file, retry_state)
                def records_by_id(path: Path) -> dict[str, dict[str, Any]]:
                    if not path.exists(): return {}
                    return {str(row["custom_id"]): row for line in path.read_text(encoding="utf-8").splitlines() if line.strip() for row in [json.loads(line)]}
                merged_output = records_by_id(original_output)
                merged_output.update(records_by_id(retry_output))
                merged_errors = records_by_id(original_errors)
                merged_errors.update(records_by_id(retry_errors))
                for custom_id in merged_output: merged_errors.pop(custom_id, None)
                original_output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in merged_output.values()) + ("\n" if merged_output else ""), encoding="utf-8")
                original_errors.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in merged_errors.values()) + ("\n" if merged_errors else ""), encoding="utf-8")
        results, errors = parse_output(root / "responses/results.jsonl")
        if original_errors.exists():
            for line in original_errors.read_text(encoding="utf-8").splitlines():
                if not line.strip(): continue
                row = json.loads(line); body = (row.get("response") or {}).get("body", {})
                error = body.get("error") or row.get("error") or "batch request failed"
                errors[str(row.get("custom_id", "unknown"))] = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        mapping_by_request = json.loads((root / "mapping.json").read_text(encoding="utf-8"))
        validated_results: dict[str, Any] = {}
        for custom_id, result in results.items():
            request_mapping = mapping_by_request.get(custom_id)
            if request_mapping is None or str(result.get("job_id")) != request_mapping["job_id"]:
                errors[custom_id] = "evaluation result job_id does not match its request"
                continue
            winner = result.get("winner")
            result["winner_variant"] = request_mapping["candidate_variants"].get(winner)
            validated_results[custom_id] = result
        usage = usage_from_output(root / "responses/results.jsonl")
        usage.update({"jobs": len(complete), "average_input_tokens_per_job": usage["input_tokens"] / len(complete) if complete else 0, "average_output_tokens_per_job": usage["output_tokens"] / len(complete) if complete else 0, "average_total_tokens_per_job": usage["total_tokens"] / len(complete) if complete else 0})
        (root / "token_usage.json").write_text(json.dumps(usage, indent=2), encoding="utf-8")
        (root / "results.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in validated_results.values()) + ("\n" if validated_results else ""), encoding="utf-8"); (root / "validation.json").write_text(json.dumps({"errors": errors}, indent=2), encoding="utf-8")
