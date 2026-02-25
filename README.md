# Gemini-Backed Brightspace Grader

This tool grades Brightspace PDF submissions with `gemini-2.5-flash`, annotates PDFs with inline green checks/red `x` marks, and builds CSV outputs for grade import and review.

## Requirements

- macOS/Linux with command-line binaries:
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
  --locator-model "gemini-3-flash-preview" \
  --output-dir "/Users/walsh.kang/Downloads/Assignment 1 Graded Feb 2026"
```

## Outputs

Inside `--output-dir`:

- Mirrored student submission folders with annotated PDFs (same names as originals)
- `brightspace_grades_import.csv`
- `grading_audit.csv`
- `review_queue.csv`
- `index_audit.csv`

## Notes

- If any question is `needs_review`, final band is `REVIEW_REQUIRED`.
- `--locator-model` is optional; if set, model-provided PDF coordinates are used before local anchor fallback.
- Grade points are configurable via CLI flags:
  - `--check-plus-points`
  - `--check-points`
  - `--check-minus-points`
  - `--review-required-points`
- `--dry-run` now defaults to header-only annotation (no per-question x/✓ marks).
- Use `--annotate-dry-run-marks` if you want debug placement marks during dry-run.
