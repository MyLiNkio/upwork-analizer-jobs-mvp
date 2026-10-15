from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .schema import schema_json

SYSTEM_PROMPT = """Extract only functionality explicitly requested in the Upwork job. Preserve exact quotations in original_fragments. Normalize faithfully without inventing facts. Keep separate independent tasks. Keep technologies and integrations only when supported by the source. Keep fragments in their original language. Do not include hiring, company, communication, rate, schedule, or generic candidate requirements unless they specify a technical constraint of the solution."""
EVALUATION_PROMPT = """You are an independent evaluator. Compare candidate outputs against the original job only. Reward complete, faithful functional extraction and verbatim evidence. Penalize hallucinations, unsupported technologies, omissions, bad quotations, and incorrectly merged or split tasks. Explain scores with concrete evidence. Candidate labels are blind and do not identify models."""


def _body(model: str, system: str, user: str, schema: dict[str, Any], reasoning: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "text": {"format": {"type": "json_schema", "name": "benchmark_result", "strict": True, "schema": schema}}}
    if reasoning: body["reasoning"] = {"effort": reasoning}
    return body


def extraction_body(model: str, job: dict[str, str], schema: dict[str, Any], reasoning: str | None = None) -> dict[str, Any]:
    user = f"JOB_ID: {job['job_id']}\nTITLE: {job['title']}\nDESCRIPTION:\n{job['description']}"
    return _body(model, SYSTEM_PROMPT, user, schema, reasoning)


def evaluation_body(model: str, job: dict[str, str], candidate_a: Any, candidate_b: Any, schema: dict[str, Any], reasoning: str | None = None) -> dict[str, Any]:
    user = json.dumps({"job_id": job["job_id"], "original_title": job["title"], "original_description": job["description"], "candidate_a": candidate_a, "candidate_b": candidate_b}, ensure_ascii=False)
    return _body(model, EVALUATION_PROMPT, user, schema, reasoning)


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
        for custom_id, body in requests.items():
            output.write(json.dumps({"custom_id": custom_id, "method": "POST", "url": "/v1/responses", "body": body}, ensure_ascii=False) + "\n")


def submit(path: Path, metadata: dict[str, str], completion_window: str) -> dict[str, Any]:
    api = client()
    with path.open("rb") as stream:
        file = api.files.create(file=stream, purpose="batch")
    batch = api.batches.create(input_file_id=file.id, endpoint="/v1/responses", completion_window=completion_window, metadata=metadata)
    return {"batch_id": batch.id, "input_file_id": file.id, "status": batch.status, "created_at": time.time()}


def sync(state: dict[str, Any], output_path: Path, error_path: Path, poll_seconds: int = 30) -> dict[str, Any]:
    api = client()
    batch = api.batches.retrieve(state["batch_id"])
    while batch.status in {"validating", "in_progress", "finalizing", "cancelling"}:
        time.sleep(poll_seconds)
        batch = api.batches.retrieve(state["batch_id"])
    state["status"] = batch.status
    state["completed_at"] = time.time()
    if batch.output_file_id:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(api.files.content(batch.output_file_id).content)
    if batch.error_file_id:
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_bytes(api.files.content(batch.error_file_id).content)
    return state


def parse_output(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    results: dict[str, Any] = {}; errors: dict[str, str] = {}
    if not path.exists(): return results, errors
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line: continue
        row = json.loads(line); custom_id = row["custom_id"]
        response = row.get("response")
        if row.get("error") or not response:
            errors[custom_id] = str(row.get("error") or "missing response"); continue
        body = response.get("body", {})
        content = body.get("output_text")
        if content is None:
            for item in body.get("output", []):
                for part in item.get("content", []):
                    if part.get("type") in {"output_text", "text"}: content = part.get("text"); break
        try: results[custom_id] = json.loads(content or "")
        except (TypeError, json.JSONDecodeError) as exc: errors[custom_id] = f"invalid JSON: {exc}"
    return results, errors
