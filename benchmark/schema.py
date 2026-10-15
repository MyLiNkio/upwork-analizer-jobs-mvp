from __future__ import annotations

import json
from typing import Any, Iterable


JOB_RESULT_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": {
    "job_id": {},
    "original_title": {"type": "string"},
    "original_text": {"type": "string"},
    "normalized_text": {"type": "string"},
    "technologies": {"type": "array", "items": {"type": "string"}},
}, "required": ["job_id", "original_title", "original_text", "normalized_text", "technologies"]}

# One schema is used for both single and multi-job requests.
EXTRACTION_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False,
    "properties": {"jobs": {"type": "array", "items": JOB_RESULT_SCHEMA}},
    "required": ["jobs"]}
BATCH_EXTRACTION_SCHEMA = EXTRACTION_SCHEMA

EVALUATION_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False,
    "properties": {
        "job_id": {}, "scores": {"type": "object", "additionalProperties": {"type": "number"}},
        "criteria": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": False,
            "properties": {"score": {"type": "number"}, "explanation": {"type": "string"}}, "required": ["score", "explanation"]}},
        "winner": {"type": "string"}, "missing_requirements": {"type": "array", "items": {"type": "string"}},
        "unsupported_information": {"type": "array", "items": {"type": "string"}},
        "technology_omissions": {"type": "array", "items": {"type": "string"}},
        "cross_job_contamination": {"type": "array", "items": {"type": "string"}},
        "incorrect_task_attribution": {"type": "array", "items": {"type": "string"}},
        "critical_errors": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"}, "needs_review": {"type": "boolean"},
    }, "required": ["job_id", "scores", "criteria", "winner", "missing_requirements", "unsupported_information", "technology_omissions", "cross_job_contamination", "incorrect_task_attribution", "critical_errors", "explanation", "needs_review"]}


def schema_json(schema: dict[str, Any]) -> str: return json.dumps(schema, ensure_ascii=False, indent=2)


def validate_result(value: Any, expected_job_id: Any, schema: dict[str, Any] = JOB_RESULT_SCHEMA) -> list[str]:
    if not isinstance(value, dict): return ["result is not an object"]
    errors: list[str] = []
    if value.get("job_id") != expected_job_id: errors.append("job_id mismatch")
    for key in schema.get("required", []):
        if key not in value: errors.append(f"missing field: {key}")
    if schema.get("additionalProperties") is False: errors.extend(f"unexpected field: {key}" for key in value if key not in schema["properties"])
    return errors


def validate_extraction_response(value: Any, jobs: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Validate count, positional identity, required fields and source quotations."""
    expected = list(jobs); errors: list[str] = []
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), list): return {}, ["missing jobs array"]
    results = value["jobs"]
    if len(results) != len(expected): errors.append(f"expected {len(expected)} results, got {len(results)}")
    indexed: dict[str, Any] = {}
    for index, item in enumerate(results):
        if index >= len(expected): errors.append(f"unexpected result at position {index}"); continue
        source = expected[index]; expected_id = source["job_id"]
        errors.extend(validate_result(item, expected_id))
        if isinstance(item, dict):
            if item.get("original_title") != source.get("title"): errors.append(f"original_title mismatch at position {index}")
            original_text = item.get("original_text", "")
            if original_text:
                fragments = [part.strip() for part in original_text.split(" [...] ")]
                if any(part and part not in source.get("description", "") for part in fragments):
                    errors.append(f"original_text is not verbatim for job_id {expected_id}")
            key = str(expected_id)
            if key in indexed:
                suffix = 2
                while f"{key}#{suffix}" in indexed: suffix += 1
                key = f"{key}#{suffix}"
            indexed[key] = item
    return indexed, errors
