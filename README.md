# Gemini-Backed Brightspace Grader

This tool grades Brightspace PDF submissions with Gemini, annotates PDFs with editable AcroForm text fields (green checks/red `x` marks), and builds CSV outputs for grade import and review.

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

## Outputs

Inside `--output-dir`:

- Mirrored student submission folders with annotated PDFs (same names as originals)
- `brightspace_grades_import.csv`
- `grading_audit.csv`
- `review_queue.csv`
- `index_audit.csv`
- `grading_diagnostics.json` (unless overridden with `--diagnostics-file`)

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
