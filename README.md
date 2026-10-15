# Upwork Analyzer Jobs MVP

Benchmark extraction and normalization of Upwork jobs with two OpenAI models and an independent evaluator.

## Setup (PowerShell)

Run these commands from the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:OPENAI_API_KEY = "your-api-key"
```

The API key is read from `$env:OPENAI_API_KEY`. Model IDs and PostgreSQL connection settings are read from `config.yaml`. `prepare` checks model availability and creates a run directory under `experiments/`.

If PowerShell blocks virtual environment activation, allow scripts for this PowerShell process and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Run lifecycle

### 1. Prepare a run

```powershell
python -m benchmark prepare
```

Checks the configured models with the OpenAI API, samples jobs from the configured database, and saves a new run. The command prints a run ID such as `run_0123456789ab`; use it in subsequent commands.

### 2. Extract jobs

Submit extraction requests to the OpenAI Batch API:

```powershell
python -m benchmark extract --run-id RUN_ID --variant all --mode submit
```

This submits all configured variants. To submit just one variant, replace `all` with `v1`, `v2`, `v3`, or `v4`:

```powershell
python -m benchmark extract --run-id RUN_ID --variant v2 --mode submit
```

The legacy `--model` option is also accepted when `--variant` is left at its default: `a` selects `v1`, `b` selects `v3`, and `all` selects all variants. Prefer `--variant` for new commands.

### 3. Wait for and collect extraction results

```powershell
python -m benchmark extract --run-id RUN_ID --variant all --mode sync
```

Checks submitted batches and waits until they finish, then downloads outputs and errors, validates extraction responses, and writes valid results. You can use a specific variant instead of `all`.

If validation rules change, rebuild accepted results from the raw responses already saved locally without contacting OpenAI:

```powershell
python -m benchmark extract --run-id RUN_ID --variant all --mode revalidate
```

### 4. Evaluate outputs

After extraction is complete for the variants you want to compare, submit blind-comparison requests to the evaluator model:

```powershell
python -m benchmark evaluate --run-id RUN_ID --mode submit
```

Evaluation automatically uses the completed variants that have valid extraction results. It supports comparing two, three, or four variants and evaluates only jobs that have a valid result in every selected variant. At least two completed variants are required.

Collect and save the evaluation batch results:

```powershell
python -m benchmark evaluate --run-id RUN_ID --mode sync
```

Evaluation includes jobs with valid extraction output in each completed variant selected for comparison.

### 5. Create a report

```powershell
python -m benchmark report --run-id RUN_ID
```

Builds the comparison report from the saved extraction and evaluation results.

## Commands and modes

The supported top-level commands are:

| Command | Purpose |
| --- | --- |
| `prepare` | Verify models, sample the database, and create a new run. Does not accept `--run-id`. |
| `extract` | Prepare and submit extraction batches, collect their results, or inspect a run through one of the modes below. Requires `--run-id`. |
| `evaluate` | Submit or collect blind evaluation batches. Requires `--run-id`. |
| `report` | Generate the report for a run. Requires `--run-id`. |
| `status` | Print the saved status for each batch state file in the run. Requires `--run-id`. |
| `resume` | Synchronize the selected extraction variant(s) for an existing run. Equivalent to `extract --mode resume`; it does not resume evaluation. Requires `--run-id`. |
| `run-all` | Create a run when no `--run-id` is given, submit and synchronize all extraction variants, submit and synchronize evaluation, then generate a report. |

Extraction and evaluation support these `--mode` values:

| Mode | Purpose |
| --- | --- |
| `dry-run` | Generate request and mapping files locally without submitting to OpenAI. For extraction and evaluation. |
| `submit` | Submit a new batch when the saved state has no `batch_id`. This is the default mode. |
| `sync` | Wait for a previously submitted batch to finish, download its output, and process the results. |
| `resume` | For extraction, synchronize an existing batch like `sync`. The top-level `resume` command invokes this mode. For evaluation it also synchronizes an existing batch. |
| `retry-failed` | Extraction submits only if the saved state has no `batch_id`. Evaluation resubmits only requests listed in the completed batch's `responses/errors.jsonl`; successful evaluations are not repeated. |

Examples:

```powershell
python -m benchmark extract --run-id RUN_ID --variant v1 --mode dry-run
python -m benchmark extract --run-id RUN_ID --variant v1 --mode submit
python -m benchmark extract --run-id RUN_ID --variant v1 --mode sync
python -m benchmark extract --run-id RUN_ID --variant v1 --mode retry-failed
python -m benchmark resume --run-id RUN_ID --variant all
python -m benchmark evaluate --run-id RUN_ID --mode dry-run
python -m benchmark status --run-id RUN_ID
python -m benchmark run-all
```

`--variant` accepts `v1`, `v2`, `v3`, `v4`, or `all`; it applies to extraction and resume. Its default is `all`. `--config PATH` selects a config file instead of `config.yaml` and can be used with any command.

## Run files

Run artifacts are stored under `experiments/RUN_ID/` (ignored by Git). The run includes a configuration snapshot, sampled dataset, prompts, request files, state files, provider responses, validation details, token usage, and results. Batch state files are written atomically.

## Ready-to-copy PowerShell workflows

Run these commands from the project directory after setup. Each block creates or uses a run as indicated. For blocks that resume an existing run, replace the example run ID with the ID printed when that run was prepared. The four variants use the same sampled dataset when run under one run ID:

| Variant | Model | Jobs per request |
| --- | --- | ---: |
| `v1` | `gpt-5.6-luna` | 1 |
| `v2` | `gpt-5.6-luna` | 100 |
| `v3` | `gpt-6-luna` | 1 |
| `v4` | `gpt-6-luna` | 100 |

### Run each variant separately

Each block creates a fresh run, submits that variant, waits for its batch to finish, and writes the report. Copy the entire block for the variant you want.

#### Variant v1

```powershell
$runId = python -m benchmark prepare
python -m benchmark extract --run-id $runId --variant v1 --mode submit
python -m benchmark extract --run-id $runId --variant v1 --mode sync
python -m benchmark report --run-id $runId
```

#### Variant v2

```powershell
$runId = python -m benchmark prepare
python -m benchmark extract --run-id $runId --variant v2 --mode submit
python -m benchmark extract --run-id $runId --variant v2 --mode sync
python -m benchmark report --run-id $runId
```

#### Variant v3

```powershell
$runId = python -m benchmark prepare
python -m benchmark extract --run-id $runId --variant v3 --mode submit
python -m benchmark extract --run-id $runId --variant v3 --mode sync
python -m benchmark report --run-id $runId
```

#### Variant v4

```powershell
$runId = python -m benchmark prepare
python -m benchmark extract --run-id $runId --variant v4 --mode submit
python -m benchmark extract --run-id $runId --variant v4 --mode sync
python -m benchmark report --run-id $runId
```

### Run all variants together

This block submits and collects all four extraction variants against the same sampled jobs, then generates the report:

```powershell
$runId = python -m benchmark prepare
python -m benchmark extract --run-id $runId --variant all --mode submit
python -m benchmark extract --run-id $runId --variant all --mode sync
python -m benchmark report --run-id $runId
```

For the full automatic workflow, including evaluator submission, result collection, and report generation:

```powershell
python -m benchmark run-all
```

### Resume each variant separately

Use the exact run ID printed by `prepare` or `run-all`. Each command synchronizes that variant's existing extraction batch and saves its results.

#### Resume v1

```powershell
$runId = "run_0123456789ab"
python -m benchmark status --run-id $runId
python -m benchmark resume --run-id $runId --variant v1
```

#### Resume v2

```powershell
$runId = "run_0123456789ab"
python -m benchmark status --run-id $runId
python -m benchmark resume --run-id $runId --variant v2
```

#### Resume v3

```powershell
$runId = "run_0123456789ab"
python -m benchmark status --run-id $runId
python -m benchmark resume --run-id $runId --variant v3
```

#### Resume v4

```powershell
$runId = "run_0123456789ab"
python -m benchmark status --run-id $runId
python -m benchmark resume --run-id $runId --variant v4
```

Resume all extraction variants in the existing run:

```powershell
$runId = "run_0123456789ab"
python -m benchmark status --run-id $runId
python -m benchmark resume --run-id $runId --variant all
```

The top-level `resume` command resumes extraction only. If an evaluation batch was already submitted, collect it separately:

```powershell
$runId = "run_0123456789ab"
python -m benchmark evaluate --run-id $runId --mode sync
python -m benchmark report --run-id $runId
```

### Compare variant results

For a fair quality comparison, run every extraction variant on the same run, then submit and collect evaluator results. Copy and run the complete block:

```powershell
$runId = python -m benchmark prepare
python -m benchmark extract --run-id $runId --variant all --mode submit
python -m benchmark extract --run-id $runId --variant all --mode sync
python -m benchmark evaluate --run-id $runId --mode submit
python -m benchmark evaluate --run-id $runId --mode sync
python -m benchmark report --run-id $runId
Write-Host "Comparison report: experiments/$runId/reports/report.md"
```

The evaluator automatically selects completed variants that have valid extraction results and compares only jobs with valid outputs in every selected variant. Reports and machine-readable comparison files are saved under `experiments/$runId/reports/`.
