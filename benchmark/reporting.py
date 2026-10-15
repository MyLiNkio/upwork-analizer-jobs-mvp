from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def report(config: dict[str, Any], run_id: str) -> None:
    root = Path(config["storage"]["base_dir"]) / run_id; evaluation = root / "evaluation/results.jsonl"
    rows = [json.loads(line) for line in evaluation.read_text(encoding="utf-8").splitlines()] if evaluation.exists() else []
    counts = {key: sum(1 for row in rows if row.get("winner") == key) for key in ("A", "B", "tie")}
    scores = [row.get("candidate_a_score", 0) for row in rows] + [row.get("candidate_b_score", 0) for row in rows]
    summary = {"run_id": run_id, "evaluated_jobs": len(rows), "wins": counts, "mean_score": sum(scores) / len(scores) if scores else None,
               "needs_review": sum(bool(row.get("needs_review")) for row in rows)}
    reports = root / "reports"; reports.mkdir(exist_ok=True)
    (reports / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    with (reports / "comparison.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["job_id", "candidate_a_score", "candidate_b_score", "winner", "needs_review"]); writer.writeheader()
        writer.writerows({key: row.get(key) for key in writer.fieldnames} for row in rows)
    review = [row for row in rows if row.get("needs_review") or row.get("winner") == "tie"]
    with (reports / "review_cases.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["job_id", "winner", "explanation"]); writer.writeheader(); writer.writerows({key: row.get(key) for key in writer.fieldnames} for row in review)
    (reports / "report.md").write_text(f"# Benchmark report\n\n- Jobs evaluated: {len(rows)}\n- Candidate A wins: {counts['A']}\n- Candidate B wins: {counts['B']}\n- Ties: {counts['tie']}\n- Cases needing review: {summary['needs_review']}\n\nResults are not a claim of superiority when the sample or judge output is incomplete.\n", encoding="utf-8")
