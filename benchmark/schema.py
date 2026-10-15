from __future__ import annotations

import json
from typing import Any, Iterable


def _task_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": {
        "original_fragments": {"type": "array", "items": {"type": "string"}},
        "normalized_task": {"type": ["string", "null"]},
        "operations": {"type": "array", "items": {"type": "string"}},
        "inputs": {"type": "array", "items": {"type": "string"}},
        "outputs": {"type": "array", "items": {"type": "string"}},
        "technologies": {"type": "array", "items": {"type": "string"}},
        "integrations": {"type": "array", "items": {"type": "string"}},
        "business_goal": {"type": ["string", "null"]},
    }, "required": ["original_fragments", "normalized_task", "operations", "inputs", "outputs", "technologies", "integrations", "business_goal"]}


JOB_RESULT_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": {
    "job_id": {"type": "string"}, "tasks": {"type": "array", "items": _task_schema()},
    "extraction_notes": {"type": "array", "items": {"type": "string"}},
}, "required": ["job_id", "tasks", "extraction_notes"]}

# Legacy single-result schema remains public for backwards compatibility.
EXTRACTION_SCHEMA: dict[str, Any] = JOB_RESULT_SCHEMA
# The response contract is identical for single and multi requests.
BATCH_EXTRACTION_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False,
    "properties": {"results": {"type": "array", "items": JOB_RESULT_SCHEMA}},
    "required": ["results"]}

EVALUATION_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False,
    "properties": {
        "job_id": {"type": "string"},
        "scores": {"type": "object", "additionalProperties": {"type": "number"}},
        "criteria": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": False,
            "properties": {"score": {"type": "number"}, "explanation": {"type": "string"}},
            "required": ["score", "explanation"]}},
        "winner": {"type": "string"},
        "missing_requirements": {"type": "array", "items": {"type": "string"}},
        "unsupported_information": {"type": "array", "items": {"type": "string"}},
        "technology_omissions": {"type": "array", "items": {"type": "string"}},
        "cross_job_contamination": {"type": "array", "items": {"type": "string"}},
        "incorrect_task_attribution": {"type": "array", "items": {"type": "string"}},
        "critical_errors": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"}, "needs_review": {"type": "boolean"},
    }, "required": ["job_id", "scores", "criteria", "winner", "missing_requirements", "unsupported_information", "technology_omissions", "cross_job_contamination", "incorrect_task_attribution", "critical_errors", "explanation", "needs_review"]}


def schema_json(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2)


def validate_result(value: Any, expected_job_id: str, schema: dict[str, Any] = JOB_RESULT_SCHEMA) -> list[str]:
    # Compatibility with the original public helper, which validated one job
    # against EXTRACTION_SCHEMA before the response envelope was introduced.
    if schema is BATCH_EXTRACTION_SCHEMA and isinstance(value, dict) and "job_id" in value:
        schema = JOB_RESULT_SCHEMA
    if not isinstance(value, dict): return ["result is not an object"]
    errors: list[str] = []
    if value.get("job_id") != expected_job_id: errors.append("job_id mismatch")
    for key in schema.get("required", []):
        if key not in value: errors.append(f"missing field: {key}")
    if schema.get("additionalProperties") is False:
        errors.extend(f"unexpected field: {key}" for key in value if key not in schema["properties"])
    return errors


def validate_extraction_response(value: Any, jobs: Iterable[dict[str, str]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Validate cardinality, identity and verbatim evidence, then index by job_id."""
    expected = {str(job["job_id"]): job for job in jobs}
    errors: list[str] = []
    if not isinstance(value, dict) or not isinstance(value.get("results"), list): return {}, ["missing results array"]
    results = value["results"]
    if len(results) != len(expected): errors.append(f"expected {len(expected)} results, got {len(results)}")
    indexed: dict[str, dict[str, Any]] = {}
    for item in results:
        job_id = str(item.get("job_id")) if isinstance(item, dict) else "<invalid>"
        if job_id in indexed: errors.append(f"duplicate job_id: {job_id}")
        if job_id not in expected: errors.append(f"unexpected job_id: {job_id}"); continue
        problems = validate_result(item, job_id)
        for task in item.get("tasks", []) if isinstance(item, dict) else []:
            for fragment in task.get("original_fragments", []):
                if fragment not in expected[job_id].get("description", "") and fragment not in expected[job_id].get("title", ""):
                    problems.append(f"quote not found for job_id {job_id}: {fragment[:80]}")
        errors.extend(problems); indexed[job_id] = item
    errors.extend(f"missing job_id: {job_id}" for job_id in expected if job_id not in indexed)
    return indexed, errors
