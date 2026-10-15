from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .schema import BATCH_EXTRACTION_SCHEMA, build_evaluation_schema

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
_EVALUATION_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "evaluation_prompt.txt"
EVALUATION_PROMPT = _EVALUATION_PROMPT_PATH.read_text(encoding="utf-8")


def _body(model: str, system: str, user_value: Any, schema: dict[str, Any], reasoning: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "input": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user_value, ensure_ascii=False)}], "text": {"format": {"type": "json_schema", "name": "benchmark_result", "strict": True, "schema": schema}}}
    if reasoning: body["reasoning"] = {"effort": reasoning}
    return body


def extraction_body(model: str, jobs: dict[str, str] | list[dict[str, str]], schema: dict[str, Any] = BATCH_EXTRACTION_SCHEMA, reasoning: str | None = None) -> dict[str, Any]:
    if isinstance(jobs, dict): jobs = [jobs]
    payload = {"jobs": [{"job_id": job["job_id"], "description": job["description"]} for job in jobs]}
    return _body(model, SYSTEM_PROMPT, payload, schema, reasoning)


def evaluation_body(model: str, original_job: dict[str, str], candidates: list[dict[str, Any]], schema: dict[str, Any] | None = None, reasoning: str | None = None) -> dict[str, Any]:
    if len(candidates) < 2 or len(candidates) > 4:
        raise ValueError(f"Evaluation requires between two and four candidates, got {len(candidates)}")
    expected_job_id = str(original_job["job_id"])
    if any(str(candidate["normalized_result"].get("job_id")) != expected_job_id for candidate in candidates):
        raise ValueError(f"Candidate job_id does not match original job_id {expected_job_id}")
    payload = {
        "original_job": {
            "job_id": expected_job_id,
            "description": original_job["description"],
        },
        "candidates": candidates,
    }
    evaluation_schema = schema or build_evaluation_schema([candidate["candidate_id"] for candidate in candidates])
    return _body(model, EVALUATION_PROMPT, payload, evaluation_schema, reasoning)


def client():
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")
    return OpenAI(api_key=api_key)


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
    if path.suffix.lower() != ".jsonl":
        raise ValueError(f"Batch input file must use the .jsonl extension: {path}")
    api = client()
    file = api.files.create(file=path, purpose="batch")
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


def usage_from_output(path: Path) -> dict[str, int]:
    """Sum provider-reported token usage from a Responses Batch output file."""
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if not path.exists(): return totals
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line: continue
        try:
            body = json.loads(line).get("response", {}).get("body", {})
            usage = body.get("usage", {})
            totals["input_tokens"] += int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
            totals["output_tokens"] += int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
            totals["total_tokens"] += int(usage.get("total_tokens", 0) or 0)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    if not totals["total_tokens"]: totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    return totals


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
