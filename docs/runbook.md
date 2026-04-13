# Gradeline Runbook

Operational reference for running a grading batch, investigating issues, and iterating on rubrics.

---

## New assignment — first run

### 1. Gather files from Brightspace

| File | Where |
|---|---|
| Submissions folder | Assignments → select assignment → Download All → unzip |
| Solutions PDF | Your answer key |
| Grade template CSV | Grades → Export → select assignment column |

### 2. Import into repo

```bash
source .venv/bin/activate
./gradeline import --profile a4
```

Copies submissions, solutions, and grade CSV from `~/Downloads` into `data/a4/`.

### 3. Generate a starter rubric

```bash
./gradeline quickstart --profile a4 --no-run
```

If no rubric exists, quickstart writes a starter `configs/a4.yaml`. Edit each question's `scoring_rules`:

- Specify the expected answer and units
- Add tolerance ranges for numerical answers: `accept ±0.01`, `accept 85.0–85.5%`
- Note cascading error cases: `treat as rounding_error if method is correct but value differs due to a carried-forward error from Q1`
- Define partial credit threshold (`partial_credit: 0.5` in the rubric header)

See `configs/_templates/rubric_sample.yaml` for a complete annotated example.

### 4. Test on one submission

```bash
python3 -m grader.cli \
  --submissions-dir "data/a4/submissions" \
  --solutions-pdf "data/a4/solutions.pdf" \
  --rubric-yaml "configs/a4.yaml" \
  --grades-template-csv "data/a4/grades.csv" \
  --grade-column "Assignment 4 Points Grade" \
  --grading-mode unified \
  --student-filter "Jane Doe" \
  --output-dir "outputs/a4"
```

Open the annotated PDF and check:
- Are the ✓/✗ marks landing near the right answers?
- Are verdicts matching your expectation?
- Is partial credit triggering correctly?

Adjust `scoring_rules` and re-run the spot test until grading looks right.

### 5. Grade the full batch

```bash
python3 -m grader.workflow_cli run --profile .manual_runs/profiles/a4.toml
```

Ctrl+C when `Review server running at http://127.0.0.1:8765` appears → choose **stop, keep results**.

### 6. Check grade distribution

```bash
python3 -c "
import csv
from collections import Counter
bands = Counter()
with open('outputs/a4/grading_audit.csv') as f:
    seen = set()
    for row in csv.DictReader(f):
        if row['folder'] not in seen:
            seen.add(row['folder'])
            bands[row['band']] += 1
for band, n in sorted(bands.items()):
    print(f'  {band}: {n}')
print(f'  Total: {sum(bands.values())}')
"
```

Spot-check 3–4 annotated PDFs across grade bands before accepting results.

### 7. Upload to Brightspace

`outputs/a4/brightspace_grades_import.csv` is ready to import directly via Brightspace Grades → Import.

---

## Re-run from scratch

```bash
rm -rf outputs/a4
rm -f .grader_cache/cache.db .grader_cache/cache.json .grader_cache/context_cache.json
python3 -m grader.workflow_cli run --profile .manual_runs/profiles/a4.toml
```

Or use the regrade command (handles cache clearing automatically):

```bash
./gradeline regrade --profile a4
```

---

## Re-run specific students

```bash
./gradeline regrade --profile a4 --student-filter "Kevin Swift|Shelly Marc"
```

Clears only those students' cache entries and output folders, then re-grades them.

---

## Iterating on rubric strictness

If results look too strict or too lenient after a full run:

1. Edit `scoring_rules` in `configs/a4.yaml`
2. If grading is too strict due to cascading errors, add explicit tolerance ranges and note that downstream errors should be treated as `rounding_error`
3. Clear cache and re-run:

```bash
rm -f .grader_cache/cache.db .grader_cache/cache.json .grader_cache/context_cache.json
python3 -m grader.workflow_cli run --profile .manual_runs/profiles/a4.toml
```

The context cache (solutions PDF + system prompt) must be cleared whenever you change the rubric, since the system prompt is part of the cached payload.

---

## Tuning performance

### Concurrency

Default is 8 parallel grading workers (set in `configs/defaults.toml`). Override per-profile:

```toml
[grade]
concurrency = 4   # lower if hitting Gemini rate limits
```

### Skip block extraction for handwritten assignments

Block extraction (Tesseract OCR → spatial bounding boxes) helps annotation placement on typed PDFs. For all-handwritten submissions it adds overhead without benefit since the model falls back to `model_coords` anyway.

```toml
[grade]
extract_blocks = false
```

### Model selection

```toml
[grade]
model = "gemini-2.5-flash"          # grading/reasoning model
extraction_model = "gemini-2.0-flash-001"  # OCR fallback model
```

Grading model handles all rubric evaluation. Extraction model is only used when Tesseract confidence is too low for block registry population.

---

## Annotation placement — what to expect

Marks are placed using a four-level fallback:

| Source | When | How |
|---|---|---|
| `block_id` | Typed PDF, OCR confidence high | Exact bounding box from Tesseract block |
| `model_coords` | Handwritten or low-confidence OCR | Normalized x/y coordinates from grading model |
| `local_anchor` | No model coords returned | Regex search for question label (e.g. `"2)"`) |
| `summary_fallback` | No placement found | Text summary appended to page 1 |

`placement_source` is recorded per-question in `grading_audit.csv`. If marks are landing in wrong places, check which source is firing and whether `block_id` lookup is populating correctly.

---

## Troubleshooting

**Grading too strict / cascading errors**
A single upstream error (e.g. SST transcription) failing 4 downstream questions is a cascading error. Fix: add explicit tolerance ranges and note `rounding_error` treatment in the relevant `scoring_rules`. Clear context cache before re-running.

**Annotation marks on wrong page**
Check `page_number` and `placement_source` in `grading_audit.csv`. If `local_anchor` is firing, it means the model didn't return coordinates and the label pattern matched the wrong occurrence. Tighten `anchor_tokens` in the rubric.

**Slow batch run / tail latency**
Last 1–2 submissions sometimes take 2–3× longer due to API variance. This is expected — the concurrency model drains results as they arrive so fast submissions don't wait on slow ones. If consistently slow, check Gemini rate limit logs or lower `concurrency`.

**`No module named 'yaml'` on run**
Virtual environment not activated. Run `source .venv/bin/activate` first.

**Context cache miss after rubric edit**
The context cache stores the system instruction + solutions PDF. Any rubric change invalidates it. Clear `.grader_cache/context_cache.json` before re-running.

**`OrgDefinedId` not found warning**
Brightspace grade template uses `Username` instead of `OrgDefinedId` — harmless, grader falls back automatically. Check `identifier_column` in your profile if you need a specific column.
