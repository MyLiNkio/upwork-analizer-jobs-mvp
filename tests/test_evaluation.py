import json

import pytest

from benchmark.openai_batch import EVALUATION_PROMPT, evaluation_body
from benchmark.schema import validate_extraction_response
from benchmark.workflow import _build_evaluation_requests


def test_evaluation_body_separates_original_job_from_four_candidates():
    original_job = {
        "job_id": "job-101",
        "description": "Integrate Stripe checkout into the existing Django application.",
    }
    candidates = [
        {
            "candidate_id": f"candidate_{index}",
            "normalized_result": {
                "job_id": "job-101",
                "original_text": "Integrate Stripe checkout",
                "normalized_text": f"Candidate {index} normalized text",
                "technologies": ["Stripe", "Django"],
            },
        }
        for index in range(1, 5)
    ]

    body = evaluation_body("evaluator-model", original_job, candidates)
    messages = body["input"]
    payload = json.loads(messages[1]["content"])

    assert messages[0]["content"] == EVALUATION_PROMPT
    assert payload["original_job"] == original_job
    assert len(payload["candidates"]) == 4
    assert [candidate["candidate_id"] for candidate in payload["candidates"]] == [
        "candidate_1", "candidate_2", "candidate_3", "candidate_4"
    ]
    assert all(candidate["normalized_result"]["job_id"] == original_job["job_id"] for candidate in payload["candidates"])


def test_evaluation_body_rejects_candidates_from_another_job():
    candidates = [
        {
            "candidate_id": f"candidate_{index}",
            "normalized_result": {"job_id": "wrong-job" if index == 4 else "job-101"},
        }
        for index in range(1, 5)
    ]

    with pytest.raises(ValueError, match="does not match original job_id"):
        evaluation_body(
            "evaluator-model",
            {"job_id": "job-101", "description": "Description"},
            candidates,
        )


def test_extraction_validator_accepts_verbatim_paragraphs_with_irrelevant_text_removed():
    job = {
        "job_id": "job-303",
        "description": "Build an assistant for customer support.\n\nWe are looking for good communication skills.\n\nIntegrate it with Slack.",
    }
    response = {
        "jobs": [{
            "job_id": "job-303",
            "original_text": "Build an assistant for customer support.\n\nIntegrate it with Slack.",
            "normalized_text": "Build a customer support assistant integrated with Slack.",
            "technologies": ["Slack"],
        }]
    }

    indexed, errors = validate_extraction_response(response, [job])

    assert errors == []
    assert indexed["job-303"]["original_text"] == response["jobs"][0]["original_text"]


def test_extraction_validator_accepts_selected_source_lines_in_order():
    job = {
        "job_id": "job-305",
        "description": "What you will do:\n• Record everyday activities.\n• Complete at least 8 hours weekly.\n• Follow simple recording guidelines",
    }
    response = {"jobs": [{
        "job_id": "job-305",
        "original_text": "Record everyday activities.\nFollow simple recording guidelines",
        "normalized_text": "Record everyday activities following guidelines.",
        "technologies": [],
    }]}

    indexed, errors = validate_extraction_response(response, [job])

    assert errors == []
    assert "job-305" in indexed


def test_extraction_validator_does_not_enforce_verbatim_excerpts():
    job = {"job_id": "job-404", "description": "Build a support assistant."}
    response = {
        "jobs": [{
            "job_id": "job-404",
            "original_text": "Create a customer service assistant.",
            "normalized_text": "Build a support assistant.",
            "technologies": [],
        }]
    }

    indexed, errors = validate_extraction_response(response, [job])

    assert errors == []
    assert "job-404" in indexed


def test_extraction_validator_keeps_valid_rows_when_another_row_in_the_request_fails():
    jobs = [
        {"job_id": "job-501", "description": "Build feature A."},
        {"job_id": "job-502", "description": "Build feature B."},
        {"job_id": "job-503", "description": "Build feature C."},
    ]
    response = {
        "jobs": [
            {
                "job_id": "job-501",
                "original_text": "Build feature A.",
                "normalized_text": "Implement feature A.",
                "technologies": [],
            },
            {
                "job_id": "job-502",
                "original_text": "Implement feature B.",
                "normalized_text": "Implement feature B.",
                "technologies": [],
                "unexpected": "field",
            },
            {
                "job_id": "job-503",
                "original_text": "Build feature C.",
                "normalized_text": "Implement feature C.",
                "technologies": [],
            },
        ]
    }

    indexed, errors = validate_extraction_response(response, jobs)

    assert list(indexed) == ["job-501", "job-503"]
    assert len(errors) == 1
    assert "job_id job-502" in errors[0]
    assert "unexpected field" in errors[0]


def test_evaluation_requests_pair_one_job_with_its_four_variant_results():
    jobs = [
        {"job_id": "job-101", "description": "Description source 101. Source text job-101"},
        {"job_id": "job-202", "description": "Description source 202. Source text job-202"},
    ]
    variant_names = ("v1", "v2", "v3", "v4")
    variants = {name: {} for name in variant_names}
    outputs = {name: {} for name in variant_names}
    for variant in variants:
        for job in jobs:
            outputs[variant][job["job_id"]] = {
                "job_id": job["job_id"],
                "original_text": f"Source text {job['job_id']}",
                "normalized_text": f"{variant} normalized text for {job['job_id']}",
                "technologies": [variant],
            }

    config = {
        "variants": variants,
        "experiment": {"random_seed": 123},
        "models": {"evaluator": "evaluator-model"},
        "processing": {"reasoning_effort": "low"},
    }
    requests, mapping, complete = _build_evaluation_requests(
        config,
        {job["job_id"]: job for job in jobs},
        outputs,
    )

    assert len(requests) == len(jobs)
    assert complete == [job["job_id"] for job in jobs]
    for custom_id, body in requests.items():
        payload = json.loads(body["input"][1]["content"])
        original = payload["original_job"]
        assert set(original) == {"job_id", "description"}
        assert len(payload["candidates"]) == 4
        expected_source = next(job for job in jobs if job["job_id"] == original["job_id"])
        assert original == expected_source
        request_mapping = mapping[custom_id]
        assert request_mapping["job_id"] == original["job_id"]
        for candidate in payload["candidates"]:
            variant = request_mapping["candidate_variants"][candidate["candidate_id"]]
            result = candidate["normalized_result"]
            assert result["job_id"] == original["job_id"]
            assert result["normalized_text"] == f"{variant} normalized text for {original['job_id']}"
            assert result["original_text"] == f"Source text {original['job_id']}"


def test_evaluation_request_builder_rejects_result_for_another_job():
    job = {"job_id": "job-101", "description": "Description source 101"}
    variants = {name: {} for name in ("v1", "v2", "v3", "v4")}
    outputs = {name: {} for name in variants}
    for variant in variants:
        outputs[variant][job["job_id"]] = {
            "job_id": "job-202" if variant == "v3" else job["job_id"],
            "original_text": "",
            "normalized_text": f"Normalized {variant}",
            "technologies": [],
        }

    config = {
        "variants": variants,
        "experiment": {"random_seed": 123},
        "models": {"evaluator": "evaluator-model"},
        "processing": {},
    }
    with pytest.raises(ValueError, match="Extraction result job_id mismatch"):
        _build_evaluation_requests(config, {job["job_id"]: job}, outputs)


def test_evaluation_request_builder_reports_variants_without_valid_outputs():
    job = {"job_id": "job-101", "description": "Description source 101"}
    variants = {name: {} for name in ("v1", "v2", "v3", "v4")}
    outputs = {
        "v1": {"job-101": {"job_id": "job-101", "original_text": "", "normalized_text": "v1", "technologies": []}},
        "v2": {},
        "v3": {"job-101": {"job_id": "job-101", "original_text": "", "normalized_text": "v3", "technologies": []}},
        "v4": {"job-101": {"job_id": "job-101", "original_text": "", "normalized_text": "v4", "technologies": []}},
    }
    config = {
        "variants": variants,
        "experiment": {"random_seed": 123},
        "models": {"evaluator": "evaluator-model"},
        "processing": {},
    }

    with pytest.raises(ValueError, match="v2: 0/1"):
        _build_evaluation_requests(config, {job["job_id"]: job}, outputs)
