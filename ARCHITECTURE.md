# Upwork Analyzer Jobs MVP — Architecture

The project is an application-layer benchmark following the ecosystem direction:

`CLI application -> existing Data Access / read-only PostgreSQL -> local experiment artifacts`

OpenAI is accessed through a provider adapter in `benchmark.openai_batch`; it owns only provider request/response mechanics. Extraction, evaluation, validation, checkpointing and reporting remain application concerns. PostgreSQL is used only by `dataset.py` during `prepare`; later stages read the immutable local `dataset/jobs.jsonl` and never query the database.

## Modules

- `config.py` — YAML loading, environment expansion and database settings.
- `dataset.py` — read-only dataset query, deterministic sampling, manifest and text hashes.
- `schema.py` — shared extraction/evaluation JSON Schema and lightweight contract checks.
- `openai_batch.py` — OpenAI model availability checks, Batch API submission/sync and JSONL parsing.
- `workflow.py` — prepare, extraction, blind evaluation and atomic state checkpoints.
- `reporting.py` — CSV, JSON and Markdown reports.
- `cli.py` — execution modes and run orchestration.

Each run is isolated under `experiments/<run_id>`. API batch IDs, request files, raw responses, errors, validation results and label mappings are retained locally. State files are atomically replaced so interrupted runs can resume without creating another batch for an already submitted request set.
