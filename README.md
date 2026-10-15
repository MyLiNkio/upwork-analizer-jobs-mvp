# Upwork Analyzer Jobs MVP

Benchmark extraction and normalization of Upwork jobs with two OpenAI models and an independent evaluator.

## Setup

```bash
python -m venv .venv
python -m pip install -e .
export OPENAI_API_KEY=...
# Model IDs and PostgreSQL connection are configured in config.yaml
```

Model IDs are deliberately supplied through environment variables. `prepare` verifies their availability before creating a run.

## CLI

```bash
python -m benchmark prepare
python -m benchmark extract --run-id RUN_ID --variant all --mode submit
python -m benchmark extract --run-id RUN_ID --variant all --mode sync
python -m benchmark extract --run-id RUN_ID --variant v2 --mode submit
python -m benchmark evaluate --run-id RUN_ID
python -m benchmark report --run-id RUN_ID
python -m benchmark status --run-id RUN_ID
python -m benchmark resume --run-id RUN_ID
python -m benchmark run-all
```

Use `--mode dry-run`, `--mode retry-failed`, or `resume` as appropriate. All artifacts are stored below `experiments/` (ignored by Git), and state files are written atomically.
