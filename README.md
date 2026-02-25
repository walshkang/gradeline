# Gemini-Backed Brightspace Grader

This tool grades Brightspace PDF submissions with Gemini, annotates PDFs with movable/editable FreeText annotations (green checks/red `x` marks), and builds CSV outputs for grade import and review.

## Requirements

- macOS/Linux
- Legacy mode only binaries:
  - `pdftotext`
  - `pdfinfo`
  - `pdftoppm`
  - `tesseract`
- Python 3.11+
- Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Environment

Set your Gemini API key:

```bash
export GEMINI_API_KEY="your_api_key_here"
```

Or create a local `.env` file in this repo root (auto-loaded by `grader.cli`):

```bash
GEMINI_API_KEY="your_api_key_here"
```

## Run

```bash
python3 -m grader.cli \
  --submissions-dir "/Users/walsh.kang/Downloads/Assignment 1 Download Feb 24, 2026 742 PM" \
  --solutions-pdf "/Users/walsh.kang/Downloads/execDC24n1soln.pdf" \
  --rubric-yaml "/Users/walsh.kang/Documents/GitHub/sda-grader/configs/assignment1.yaml" \
  --grades-template-csv "/path/to/brightspace_export_template.csv" \
  --grade-column "Assignment 1 Points Grade" \
  --identifier-column "OrgDefinedId" \
  --grading-mode unified \
  --model "gemini-3-flash-preview" \
  --output-dir "/Users/walsh.kang/Downloads/Assignment 1 Graded Feb 2026"
```

Optional CLI UX and diagnostics flags:

```bash
# force plain text output (no Rich formatting)
--plain

# write diagnostics JSON to a custom path
--diagnostics-file "/custom/path/grading_diagnostics.json"

# use legacy OCR/text + optional locator pass
--grading-mode legacy --locator-model "gemini-3-flash-preview"

# context cache controls for unified mode
--context-cache --context-cache-ttl-seconds 86400
```

## Workflow CLI (Profile-Based)

Use workflow profiles to avoid long flag lists for repeated assignment runs.

### 1) Quickstart (recommended)

```bash
python3 -m grader.workflow_cli quickstart --profile a2
```

Quickstart behavior:
- Detects defaults from existing profile values, prior successful runs, and a bounded `~/Downloads` scan.
- Shows one confirmation table with optional field edits.
- Writes the profile to `.manual_runs/profiles/a2.toml`.
- Runs grading + review server immediately by default.

Write profile only (do not run yet):

```bash
python3 -m grader.workflow_cli quickstart --profile a2 --no-run
```

If the rubric path does not exist, quickstart can generate a starter rubric and prints a concise checklist:
- update `scoring_rules` per question
- confirm `label_patterns` and `anchor_tokens`
- verify grading bands thresholds

### 2) Manual setup wizard (fallback)

```bash
mkdir -p .manual_runs/profiles
cp configs/workflow_profile.example.toml .manual_runs/profiles/a2.toml
```

Edit `.manual_runs/profiles/a2.toml` with your Assignment 2 paths.

Or use the interactive wizard:

```bash
python3 -m grader.workflow_cli setup --profile a2
```

The wizard prompts for:
- submissions folder
- solutions PDF (right answers)
- rubric YAML path (and can generate a starter rubric file)
- Brightspace grade template CSV + grade column
- output directory and review host/port

### 3) Run full workflow (grade + init + serve)

```bash
python3 -m grader.workflow_cli run --profile a2
```

Behavior:
- Loads `.manual_runs/profiles/a2.toml`
- Runs `grader.cli` with mapped flags
- Initializes review state
- Starts review server on the requested port, or next free port (`+1`, up to 25 attempts)
- If profile is missing (interactive terminal), CLI offers:
  - `quickstart` first (recommended)
  - `setup` fallback
  - abort
- In non-interactive mode, missing-profile behavior remains an explicit error.

### 4) Keep Assignment 1 and Assignment 2 open side-by-side

Terminal A:

```bash
python3 -m grader.workflow_cli serve --profile a1 --port 8765
```

Terminal B:

```bash
python3 -m grader.workflow_cli run --profile a2
```

### 5) List profiles and state status

```bash
python3 -m grader.workflow_cli list
```

The list view includes:
- profile name
- output directory
- rubric path
- review state status (`valid`, `missing`, or `invalid:<reason>`)

### Troubleshooting

- `Profile file not found`: confirm profile is under `.manual_runs/profiles/<name>.toml` or pass an explicit path.
- `Unknown keys in [grade]`: remove unsupported keys; profile validation is strict by design.
- `Review state invalid`: run workflow `run` once, or run `grader.review_cli init --output-dir ...` manually.
- `Requested grade column was not found`: ensure profile `grade_column` matches your Brightspace template header.

## Outputs

Inside `--output-dir`:

- Mirrored student submission folders with annotated PDFs (same names as originals)
- `brightspace_grades_import.csv`
- `grading_audit.csv`
- `review_queue.csv`
- `index_audit.csv`
- `grading_diagnostics.json` (unless overridden with `--diagnostics-file`)

## Manual Review Web App (Local)

After a grading run finishes, you can do a second-pass manual review in a local browser app.

### 1) Initialize review state

```bash
python3 -m grader.review_cli init --output-dir "/path/to/grading/output"
```

Optional rubric override:

```bash
python3 -m grader.review_cli init \
  --output-dir "/path/to/grading/output" \
  --rubric-yaml "/path/to/rubric.yaml"
```

### 2) Start review server

```bash
python3 -m grader.review_cli serve --output-dir "/path/to/grading/output"
```

Then open `http://127.0.0.1:8765`.

Use the **Config** tab to inspect/update:
- solutions/rubric paths captured from the CLI run
- grade points mapping
- rubric thresholds (`check_plus_min`, `check_min`), `partial_credit`
- question label patterns and scoring rules (what the CLI is using as grading interpretation)

### 3) Export reviewed artifacts

```bash
python3 -m grader.review_cli export --output-dir "/path/to/grading/output"
```

Reviewed artifacts are written into `output_dir/review/`:

- `review_state.json`
- `review_events.jsonl`
- `reviewed_pdfs/...`
- `grading_audit_reviewed.csv`
- `review_queue_reviewed.csv`
- `brightspace_grades_import_reviewed.csv`
- `review_decisions.json`

## Notes

- If any question is `needs_review`, final band is `REVIEW_REQUIRED`.
- `--grading-mode` defaults to `legacy` for phased rollout.
- In `unified` mode, grading and coordinate locating happen in one structured Gemini call.
- In `legacy` mode, `--locator-model` is optional; if set, model-provided PDF coordinates are used before local anchor fallback.
- In `unified` mode, `--locator-model` and `--ocr-char-threshold` are ignored with warnings.
- Unified mode uses Gemini context caching for `solutions.pdf` unless `--no-context-cache` is passed.
- Grade points are configurable via CLI flags:
  - `--check-plus-points`
  - `--check-points`
  - `--check-minus-points`
  - `--review-required-points`
- `--dry-run` now defaults to header-only annotation (no per-question x/✓ marks).
- Use `--annotate-dry-run-marks` if you want debug placement marks during dry-run.
- Rich console output is used automatically in interactive terminals; use `--plain` for deterministic text output.
- While grading runs, a single in-place status line updates stage progress (extracting, grading, locating, annotating), including question-level annotation progress like `annotating question 1a (3/7)`.
- Diagnostics JSON includes:
  - `run_id`, `started_at`, `ended_at`, `args_snapshot`, `totals`, `events`
  - event fields: `timestamp`, `severity`, `code`, `stage`, `submission_folder`, `message`, `exception_type`, `traceback_snippet`
