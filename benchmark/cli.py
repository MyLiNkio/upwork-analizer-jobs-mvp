from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .reporting import report
from .workflow import evaluate, extract, prepare, run_dir


def main() -> None:
    parser = argparse.ArgumentParser(prog="benchmark")
    parser.add_argument("command", choices=["prepare", "extract", "evaluate", "report", "status", "resume", "run-all"])
    parser.add_argument("--run-id"); parser.add_argument("--model", choices=["a", "b", "all"], default="all")
    parser.add_argument("--mode", choices=["dry-run", "submit", "sync", "resume", "retry-failed"], default="submit")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args(); config = load_config(args.config)
    if args.command == "prepare": print(prepare(config, args.config)); return
    if args.command == "run-all" and not args.run_id:
        args.run_id = prepare(config, args.config)
        print(f"Prepared {args.run_id}")
    if not args.run_id: raise SystemExit("--run-id is required for this command")
    if args.command == "extract": extract(config, args.run_id, args.model, args.mode)
    elif args.command == "evaluate": evaluate(config, args.run_id, args.mode)
    elif args.command == "report": report(config, args.run_id)
    elif args.command == "resume": extract(config, args.run_id, args.model, "resume")
    elif args.command == "status":
        root = run_dir(config, args.run_id)
        for path in root.rglob("state.json"):
            print(path.relative_to(root), json.loads(path.read_text(encoding="utf-8")).get("status"))
    elif args.command == "run-all":
        extract(config, args.run_id, "all", "submit")
        extract(config, args.run_id, "all", "sync")
        evaluate(config, args.run_id, "submit")
        evaluate(config, args.run_id, "sync")
        report(config, args.run_id)


if __name__ == "__main__": main()
