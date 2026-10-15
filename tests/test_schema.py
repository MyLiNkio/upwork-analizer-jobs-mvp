import json

from benchmark.schema import EXTRACTION_SCHEMA, validate_result


def test_extraction_schema_requires_contract_fields():
    assert "tasks" in EXTRACTION_SCHEMA["required"]
    assert validate_result({"job_id": "1"}, "1", EXTRACTION_SCHEMA)


def test_valid_result_passes_basic_validation():
    value = {"job_id": "1", "tasks": [], "extraction_notes": []}
    assert validate_result(value, "1", EXTRACTION_SCHEMA) == []
    assert json.dumps(value)
