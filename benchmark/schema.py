from __future__ import annotations

import json
from typing import Any


EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "job_id": {"type": "string"},
        "tasks": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {
                "original_fragments": {"type": "array", "items": {"type": "string"}},
                "normalized_task": {"type": ["string", "null"]},
                "operations": {"type": "array", "items": {"type": "string"}},
                "inputs": {"type": "array", "items": {"type": "string"}},
                "outputs": {"type": "array", "items": {"type": "string"}},
                "technologies": {"type": "array", "items": {"type": "string"}},
                "integrations": {"type": "array", "items": {"type": "string"}},
                "business_goal": {"type": ["string", "null"]},
            },
            "required": ["original_fragments", "normalized_task", "operations", "inputs", "outputs", "technologies", "integrations", "business_goal"]
        }},
        "extraction_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["job_id", "tasks", "extraction_notes"],
}

EVALUATION_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "job_id": {"type": "string"}, "candidate_a_score": {"type": "number"},
        "candidate_b_score": {"type": "number"}, "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "criteria": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": False,
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}, "explanation": {"type": "string"}},
            "required": ["a", "b", "explanation"]}},
        "critical_errors": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "unsupported_additions": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"}, "needs_review": {"type": "boolean"},
    },
    "required": ["job_id", "candidate_a_score", "candidate_b_score", "winner", "criteria", "critical_errors", "missing_information", "unsupported_additions", "explanation", "needs_review"],
}


def schema_json(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2)


def validate_result(value: Any, expected_job_id: str, schema: dict[str, Any]) -> list[str]:
    """Small dependency-free contract check; provider JSON schema remains authoritative."""
    if not isinstance(value, dict): return ["result is not an object"]
    errors = []
    if value.get("job_id") != expected_job_id: errors.append("job_id mismatch")
    for key in schema.get("required", []):
        if key not in value: errors.append(f"missing field: {key}")
    if schema.get("additionalProperties") is False:
        errors.extend(f"unexpected field: {key}" for key in value if key not in schema["properties"])
    return errors
