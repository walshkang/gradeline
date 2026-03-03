# Gemini-Backed Brightspace Grader

This tool grades Brightspace PDF submissions with Gemini, annotates PDFs with movable/editable FreeText annotations (green checks/red `x` marks), and builds CSV outputs for grade import and review.

It is specifically optimized for instructors using **D2L Brightspace** who download PDF submissions and want a repeatable, profile-based grading workflow with a built-in review web app. It natively understands Brightspace's "Download All" ZIP structure, auto-detects `OrgDefinedId` or usernames, and outputs import-ready CSVs that match the Brightspace gradebook format.

## You’ll need

- A Brightspace course with at least one PDF-based assignment
- A Google Gemini API key
- macOS or Linux
- Python 3.11+ and the dependencies from `requirements.txt`

## Quick Start

```bash
# 1. Activate the virtual environment
source .venv/bin/activate

# 2. Set your Gemini API key (or add to .env file)
export GEMINI_API_KEY="your_api_key_here"

# 3. Import your assignment files from Downloads into data/{profile}/
./gradeline import --profile a2

# 4. Run the quickstart wizard for that assignment
./gradeline quickstart --profile a2
```

> **First time?** Download your student submissions, answer key PDF, and grade CSV from Brightspace into `~/Downloads`, then run `./gradeline import --profile a2`. See [`data/README.md`](data/README.md) for the expected `data/{profile}/` structure.

Running `./gradeline` with no arguments opens an interactive menu:

```
› quickstart  —  Auto-detect settings, grade, and review
  run         —  Grade submissions and launch review server
  regrade     —  Clear cache and re-run grading from scratch
  serve       —  Launch review server for existing results
  setup       —  Interactive profile setup wizard
  list        —  List local workflow profiles
```

All commands can also be called directly:

```bash
./gradeline import --profile a2
./gradeline quickstart --profile a2
./gradeline run --profile a2
./gradeline regrade --profile a2
./gradeline serve --profile a2
./gradeline list
```

## Requirements

- macOS/Linux
- Python 3.11+
- Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

- Legacy mode only binaries (not needed for unified mode):
  - `pdftotext`, `pdfinfo`, `pdftoppm`, `tesseract`

## Environment

Set your Gemini API key:

```bash
export GEMINI_API_KEY="your_api_key_here"
```

Or create a local `.env` file in this repo root (auto-loaded by `grader.cli`):

```bash
GEMINI_API_KEY="your_api_key_here"
```

## Workflow CLI (Profile-Based)

Use workflow profiles to avoid long flag lists for repeated assignment runs. The `./gradeline` wrapper auto-activates the `.venv` and delegates to the workflow CLI.

At a high level:

1. Download submissions, solutions, and a grade template CSV from Brightspace into `~/Downloads`.
2. Use `./gradeline import --profile a2` to copy them into `data/a2/`.
3. Use `./gradeline quickstart --profile a2` to auto-detect paths, confirm settings, and write a reusable profile.
4. Use `./gradeline run --profile a2` (or `regrade`/`serve`) to repeat the workflow.

See [`data/README.md`](data/README.md) for examples of how to lay out `data/{profile}/`.

### 1) Quickstart (recommended)

```bash
./gradeline quickstart --profile a2
```

Quickstart behavior:
- Detects defaults from existing profile values, prior successful runs, and a bounded `~/Downloads` scan.
- Shows one confirmation table with optional field edits.
- Writes the profile to `.manual_runs/profiles/a2.toml`.
- Runs grading + review server immediately by default.

Write profile only (do not run yet):

```bash
./gradeline quickstart --profile a2 --no-run
```

If the rubric path does not exist, quickstart can generate a starter rubric and prints a concise checklist:
- update `scoring_rules` per question
- confirm `label_patterns` and `anchor_tokens`
- verify grading bands thresholds

### 2) Manual setup wizard (fallback)

```bash
./gradeline setup --profile a2
```

The wizard prompts for:
- submissions folder
- solutions PDF (right answers)
- rubric YAML path (and can generate a starter rubric file)
- Brightspace grade template CSV + grade column
- output directory and review host/port

### 3) Import from Downloads into data/{profile}/

```bash
./gradeline import --profile a2
```

Behavior:

- Scans `~/Downloads` (or `--downloads-dir`) for a recent Brightspace submissions folder, a solutions PDF, and a grade CSV.
- Optionally handles Brightspace ZIPs by extracting them before import.
- Copies or moves (with `--move`) those assets into `data/{profile}/submissions`, `data/{profile}/solutions.pdf`, and `data/{profile}/grades.csv`.
- Prints a clear preview of what will be copied where before making changes.

### 4) Run full workflow (grade + init + serve)

```bash
./gradeline run --profile a2
```

Behavior:
- Loads `.manual_runs/profiles/a2.toml`
- Runs grading with mapped flags
- Initializes review state
- Starts review server on the requested port, or next free port (`+1`, up to 25 attempts)
- If profile is missing (interactive terminal), CLI offers quickstart, setup, or abort

### 5) Regrade (clear cache and re-run)

```bash
# Full regrade — clears all cache, outputs, and review state
./gradeline regrade --profile a2

# Regrade specific students only
./gradeline regrade --profile a2 --student-filter "Kevin Swift|Shelly Marc"
```

Regrade behavior:
- Deletes local results cache entries (all, or matching `--student-filter` regex)
- Removes annotated PDF output folders
- Full regrade also clears CSV artifacts, diagnostics, and review state
- Re-runs grading with fresh Gemini API calls
- Launches review server when done

### 6) Keep Assignment 1 and Assignment 2 open side-by-side

Terminal A:

```bash
./gradeline serve --profile a1 --port 8765
```

Terminal B:

```bash
./gradeline run --profile a2
```

### 7) List profiles and state status

```bash
./gradeline list
```

The list view includes:
- profile name
- output directory
- rubric path
- review state status (`valid`, `missing`, or `invalid:<reason>`)

### Troubleshooting

- `Profile file not found`: confirm profile is under `.manual_runs/profiles/<name>.toml` or pass an explicit path.
- `Unknown keys in [grade]`: remove unsupported keys; profile validation is strict by design.
- `Review state invalid`: run `./gradeline run` once, or run `grader.review_cli init --output-dir ...` manually.
- `Requested grade column was not found`: ensure profile `grade_column` matches your Brightspace template header.
- Quickstart shows everything as `<missing>`:
  - Make sure your assignment files are either in `data/{profile}/` or in `~/Downloads`.
  - Try running `./gradeline import --profile {profile}` to populate `data/{profile}/` first.

## Direct CLI Usage

For advanced usage or scripting, you can bypass profiles and call the grading engine directly:

```bash
python3 -m grader.cli \
  --submissions-dir "/path/to/submissions" \
  --solutions-pdf "/path/to/solutions.pdf" \
  --rubric-yaml "/path/to/rubric.yaml" \
  --grades-template-csv "/path/to/template.csv" \
  --grade-column "Assignment 1 Points Grade" \
  --grading-mode unified \
  --model "gemini-2.5-flash" \
  --output-dir "/path/to/output"
```

Optional flags:

```bash
--plain                          # force plain text output (no Rich formatting)
--diagnostics-file "/custom/path/grading_diagnostics.json"
--grading-mode legacy            # use legacy OCR/text + optional locator pass
--grading-mode agent             # agentic mode: uses an external CLI agent for multi-step reasoning
--agent-type "gemini"            # choices: gemini (default), codex, claude
--locator-model "gemini-3-flash-preview"
--context-cache --context-cache-ttl-seconds 86400
--student-filter "Jane Doe"      # regex to grade specific students only
--dry-run                        # skip API calls, test annotation layout
```

## Outputs

Inside `--output-dir`:

- Mirrored student submission folders with annotated PDFs (same names as originals)
- `brightspace_grades_import.csv`
- `grading_audit.csv`
- `review_queue.csv`
- `index_audit.csv`
- `grading_diagnostics.json` (unless overridden with `--diagnostics-file`)

## Manual Review Web App (Local)

After a grading run finishes, a local browser app launches for second-pass manual review. The review server is started automatically by `./gradeline run` and `./gradeline regrade`.

To start the review server manually:

```bash
./gradeline serve --profile a2
```

Then open the URL shown in the terminal (default `http://127.0.0.1:8765`).

Use the **Config** tab to inspect/update:
- solutions/rubric paths captured from the CLI run
- grade points mapping
- rubric thresholds (`check_plus_min`, `check_min`), `partial_credit`
- question label patterns and scoring rules

### Export reviewed artifacts

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
- In `agent` mode, the tool uses an installed CLI agent (like `gemini`, `codex`, or `claude`) to perform multi-step reasoning. This is often more robust for complex or handwritten submissions.
- `gemini` agent requires the `gemini` CLI.
- `codex` agent requires the `codex` CLI.
- `claude` agent requires the `claude` CLI (Claude Code).
- In `legacy` mode, `--locator-model` is optional; if set, model-provided PDF coordinates are used before local anchor fallback.
- In `unified` mode, `--locator-model` and `--ocr-char-threshold` are ignored with warnings.
- Unified mode uses Gemini context caching for `solutions.pdf` unless `--no-context-cache` is passed.
- Grade points are configurable via CLI flags: `--check-plus-points`, `--check-points`, `--check-minus-points`, `--review-required-points`.
- `--dry-run` defaults to header-only annotation (no per-question x/✓ marks). Use `--annotate-dry-run-marks` for debug placement marks.
- Rich console output with section headings, colored bands, and progress bars is used automatically in interactive terminals; use `--plain` for deterministic text output.
