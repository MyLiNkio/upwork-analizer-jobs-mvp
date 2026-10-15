from __future__ import annotations

import json
from typing import Any, Iterable


JOB_RESULT_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": {
    "job_id": {"type": "string"},
    "original_text": {"type": "string"},
    "normalized_text": {"type": "string"},
    "technologies": {"type": "array", "items": {"type": "string"}},
}, "required": ["job_id", "original_text", "normalized_text", "technologies"]}

# One schema is used for both single and multi-job requests.
EXTRACTION_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False,
    "properties": {"jobs": {"type": "array", "items": JOB_RESULT_SCHEMA}},
    "required": ["jobs"]}
BATCH_EXTRACTION_SCHEMA = EXTRACTION_SCHEMA

_EVALUATION_CRITERIA = [
    "functional_completeness",
    "absence_of_hallucinations",
    "technology_and_integration_preservation",
    "source_task_extraction_accuracy",
    "normalization_quality",
    "multi_task_extraction_quality",
]
_EVALUATION_CANDIDATES = ["candidate_1", "candidate_2", "candidate_3", "candidate_4"]
_CRITERION_SCORE_SCHEMA = {"type": "number", "minimum": 0, "maximum": 10}
_CRITERION_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "score": _CRITERION_SCORE_SCHEMA,
        "explanation": {"type": "string"},
    },
    "required": ["score", "explanation"],
}

def build_evaluation_schema(candidate_ids: list[str]) -> dict[str, Any]:
    return {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "job_id": {"type": "string"},
        "scores": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                candidate_id: _CRITERION_SCORE_SCHEMA for candidate_id in candidate_ids
            },
            "required": candidate_ids,
        },
        "criteria": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                candidate_id: {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {criterion: _CRITERION_REVIEW_SCHEMA for criterion in _EVALUATION_CRITERIA},
                    "required": _EVALUATION_CRITERIA,
                }
                for candidate_id in candidate_ids
            },
            "required": candidate_ids,
        },
        "winner": {"type": "string", "enum": candidate_ids},
        "missing_requirements": {"type": "array", "items": {"type": "string"}},
        "unsupported_information": {"type": "array", "items": {"type": "string"}},
        "technology_omissions": {"type": "array", "items": {"type": "string"}},
        "cross_job_contamination": {"type": "array", "items": {"type": "string"}},
        "incorrect_task_attribution": {"type": "array", "items": {"type": "string"}},
        "critical_errors": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
        "needs_review": {"type": "boolean"},
    },
    "required": [
        "job_id", "scores", "criteria", "winner", "missing_requirements",
        "unsupported_information", "technology_omissions", "cross_job_contamination",
        "incorrect_task_attribution", "critical_errors", "explanation", "needs_review",
    ],
}


EVALUATION_SCHEMA: dict[str, Any] = build_evaluation_schema(_EVALUATION_CANDIDATES)


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
    """Validate rows by job ID so one omitted or reordered result cannot shift the rest."""
    expected = list(jobs); errors: list[str] = []
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), list): return {}, ["missing jobs array"]
    results = value["jobs"]
    if len(results) != len(expected): errors.append(f"expected {len(expected)} results, got {len(results)}")
    sources = {str(source["job_id"]): source for source in expected}
    indexed: dict[str, Any] = {}
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            errors.append(f"result at position {index} is not an object")
            continue
        result_id = str(item.get("job_id", ""))
        source = sources.get(result_id)
        if source is None:
            errors.append(f"unexpected result at position {index} for job_id {result_id!r}")
            continue
        expected_id = source["job_id"]
        row_errors = validate_result(item, expected_id)
        if row_errors:
            errors.extend(f"job_id {expected_id}, result {index}: {problem}" for problem in row_errors)
            continue
        key = str(expected_id)
        if key in indexed:
            errors.append(f"duplicate result for job_id {expected_id} at position {index}")
            continue
        indexed[key] = item
    for source in expected:
        key = str(source["job_id"])
        if key not in {str(item.get("job_id", "")) for item in results if isinstance(item, dict)}:
            errors.append(f"missing result for job_id {key}")
    return indexed, errors
