from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schema import BATCH_EXTRACTION_SCHEMA, EVALUATION_SCHEMA

SYSTEM_PROMPT = """Analyze each Upwork job independently. Extract only functionality explicitly requested in that job. Never transfer technologies, tasks, business problems, or facts between jobs. Return one result with the unchanged job_id for every input job, including an empty tasks array when appropriate. Preserve exact quotations in original_fragments; they must occur verbatim in that job's title or description. Normalize faithfully without inventing facts, preserve technologies and integrations, and keep independent tasks separate. Exclude hiring, company, communication, rate, schedule, generic candidate requirements, skills, taxonomies, and prior AI classifications unless they state a technical constraint of the solution."""
EVALUATION_PROMPT = """You are an independent blind evaluator. Compare four candidate outputs only against the original Upwork job. Score each candidate independently for functional completeness (30%), absence of hallucinations (20%), technology and integration preservation (20%), verbatim extraction accuracy (15%), normalization quality (10%), and multi-task extraction quality (5%). Identify missing requirements, unsupported information, technology omissions, cross-job contamination, incorrect task attribution, and critical errors. Candidate labels are opaque and do not identify models or request grouping."""


def _body(model: str, system: str, user_value: Any, schema: dict[str, Any], reasoning: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "input": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user_value, ensure_ascii=False)}], "text": {"format": {"type": "json_schema", "name": "benchmark_result", "strict": True, "schema": schema}}}
    if reasoning: body["reasoning"] = {"effort": reasoning}
    return body


def extraction_body(model: str, jobs: dict[str, str] | list[dict[str, str]], schema: dict[str, Any] = BATCH_EXTRACTION_SCHEMA, reasoning: str | None = None) -> dict[str, Any]:
    if isinstance(jobs, dict): jobs = [jobs]
    return _body(model, SYSTEM_PROMPT, {"jobs": jobs}, schema, reasoning)


def evaluation_body(model: str, job: dict[str, str], candidates: list[Any] | tuple[Any, ...], schema: dict[str, Any] = EVALUATION_SCHEMA, reasoning: str | None = None) -> dict[str, Any]:
    return _body(model, EVALUATION_PROMPT, {"job": job, "candidates": list(candidates)}, schema, reasoning)


def client():
    from openai import OpenAI
    return OpenAI()


def verify_models(models: dict[str, str]) -> None:
    api = client()
    for role, model in models.items():
        try: api.models.retrieve(model)
        except Exception as exc: raise RuntimeError(f"Model '{model}' ({role}) is not available") from exc


def write_requests(path: Path, requests: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for custom_id, body in requests.items(): output.write(json.dumps({"custom_id": custom_id, "method": "POST", "url": "/v1/responses", "body": body}, ensure_ascii=False) + "\n")


def submit(path: Path, metadata: dict[str, str], completion_window: str) -> dict[str, Any]:
    api = client()
    with path.open("rb") as stream: file = api.files.create(file=stream, purpose="batch")
    batch = api.batches.create(input_file_id=file.id, endpoint="/v1/responses", completion_window=completion_window, metadata=metadata)
    return {"batch_id": batch.id, "input_file_id": file.id, "status": batch.status, "created_at": time.time()}


def sync(state: dict[str, Any], output_path: Path, error_path: Path, poll_seconds: int = 30) -> dict[str, Any]:
    api = client(); batch = api.batches.retrieve(state["batch_id"])
    while batch.status in {"validating", "in_progress", "finalizing", "cancelling"}:
        time.sleep(poll_seconds); batch = api.batches.retrieve(state["batch_id"])
    state.update(status=batch.status, completed_at=time.time())
    if batch.output_file_id: output_path.parent.mkdir(parents=True, exist_ok=True); output_path.write_bytes(api.files.content(batch.output_file_id).content)
    if batch.error_file_id: error_path.parent.mkdir(parents=True, exist_ok=True); error_path.write_bytes(api.files.content(batch.error_file_id).content)
    return state


def parse_output(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    results: dict[str, Any] = {}; errors: dict[str, str] = {}
    if not path.exists(): return results, errors
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line: continue
        row = json.loads(line); custom_id = row["custom_id"]; response = row.get("response")
        if row.get("error") or not response: errors[custom_id] = str(row.get("error") or "missing response"); continue
        body = response.get("body", {}); content = body.get("output_text")
        if content is None:
            content = next((part.get("text") for item in body.get("output", []) for part in item.get("content", []) if part.get("type") in {"output_text", "text"}), None)
        try: results[custom_id] = json.loads(content or "")
        except (TypeError, json.JSONDecodeError) as exc: errors[custom_id] = f"invalid JSON: {exc}"
    return results, errors
