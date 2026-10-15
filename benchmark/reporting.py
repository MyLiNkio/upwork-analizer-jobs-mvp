from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def _variant_stats(root: Path, variant: str) -> dict[str, Any]:
    extraction = root / "extraction" / variant; rows = _read_jsonl(extraction / "results.jsonl")
    state = json.loads((extraction / "state.json").read_text()) if (extraction / "state.json").exists() else {}
    mapping = json.loads((extraction / "request_mapping.json").read_text()) if (extraction / "request_mapping.json").exists() else {}
    expected = sum(len(x.get("job_ids", [])) for x in mapping.values())
    return {"variant": variant, "jobs": len(rows), "expected_jobs": expected, "job_completion_rate": len(rows) / expected if expected else None, "requests": len(mapping), "status": state.get("status", "not_started"), "jobs_per_request": state.get("jobs_per_request")}


def report(config: dict[str, Any], run_id: str) -> None:
    root = Path(config["storage"]["base_dir"]) / run_id; reports = root / "reports"; reports.mkdir(exist_ok=True)
    variants = list(config.get("variants", {"v1": {}, "v2": {}, "v3": {}, "v4": {}})); stats = [_variant_stats(root, v) for v in variants]
    evaluations = _read_jsonl(root / "evaluation/results.jsonl")
    summary: dict[str, Any] = {"run_id": run_id, "variants": stats, "evaluated_jobs": len(evaluations), "evaluation_errors": len(_read_jsonl(root / "evaluation/errors.jsonl"))}
    (reports / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    # Keep a machine-readable per-job evaluation export even when the judge has not run yet.
    with (reports / "comparison.csv").open("w", newline="", encoding="utf-8") as output:
        fields = ["job_id", "winner", "needs_review", "scores", "explanation"]; writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for row in evaluations: writer.writerow({field: json.dumps(row.get(field), ensure_ascii=False) if isinstance(row.get(field), (dict, list)) else row.get(field) for field in fields})
    review = [row for row in evaluations if row.get("needs_review") or row.get("critical_errors")]
    with (reports / "review_cases.csv").open("w", newline="", encoding="utf-8") as output:
        fields = ["job_id", "winner", "critical_errors", "explanation"]; writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for row in review: writer.writerow({field: json.dumps(row.get(field), ensure_ascii=False) if isinstance(row.get(field), list) else row.get(field) for field in fields})
    lines = ["# Benchmark report", "", "## A. Overall Ranking", "", "| Variant | Jobs | Completion | Requests | Status |", "|---|---:|---:|---:|---|"]
    lines += [f"| {s['variant']} | {s['jobs']} | {s['job_completion_rate'] if s['job_completion_rate'] is not None else 'n/a'} | {s['requests']} | {s['status']} |" for s in stats]
    lines += ["", "## B. Single vs Multi Impact", "", "Comparison is computed only from jobs with valid outputs for both variants; missing or failed jobs are not silently replaced."]
    for a, b in (("v1", "v2"), ("v3", "v4")):
        sa, sb = next((x for x in stats if x["variant"] == a), {}), next((x for x in stats if x["variant"] == b), {})
        lines.append(f"- **{a} vs {b}:** completion {sa.get('job_completion_rate', 'n/a')} → {sb.get('job_completion_rate', 'n/a')}; requests {sa.get('requests', 'n/a')} → {sb.get('requests', 'n/a')}.")
    lines += ["", "## C. Model Comparison", "", "V1/V2 use extractor A and V3/V4 use extractor B as configured. Quality is reported after evaluation is available.", "", "## D. Detailed Job Comparison", "", f"Evaluated jobs: {len(evaluations)}. Full JSON/CSV exports are in `{reports.name}/`.", "", "Results do not claim superiority when the sample, judge, or any variant is incomplete."]
    (reports / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (reports / "comparison.json").write_text(json.dumps(evaluations, indent=2, ensure_ascii=False), encoding="utf-8")
