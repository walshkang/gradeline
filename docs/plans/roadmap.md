# Gradeline Unified Roadmap

This document is the single source of truth for all planned improvements. It merges the [stability & decomposition plan](stability-decomposition-browser-first.md) with the [feedback & improvements log](../feedback.md), de-duplicates overlapping items, and organizes active tasks into execution waves with copy-pasteable agent prompts.

> [!IMPORTANT]
> **Agent Roadmap Maintenance Protocol**:
> 1. **Completion & Verification**: When an agent completes a task, runs tests, and verifies completion, update the task's status in the **Master Status Table** below from `Planned` to `✅ Done`.
> 2. **Prompt Archiving**: Move the task's detailed specification block/prompt out of `roadmap.md` and append it to [shipped-waves-archive.md](archive/shipped-waves-archive.md).
> 3. **Keep Roadmap Lean**: `roadmap.md` MUST only contain active/planned prompts and the master status table to minimize context window bloat for AI agents.

> [!NOTE]
> Items marked ✅ have been verified as shipped in the current codebase via git history and code audit. Detailed prompt specifications for shipped Waves 1–5 are archived in [shipped-waves-archive.md](archive/shipped-waves-archive.md).

---

## Master Status Table

| Wave | Task ID | Title | Size | Tier | Status | Origin |
|:---:|:---:|:---|:---:|:---:|:---:|:---|
| — | S-1 | Test Hygiene & Gitignore | S | Flash | ✅ Done | Plan Phase 1 |
| — | F-5 | CPU Bottlenecks on Large PDFs | M | Flash | ✅ Done | Feedback #5 |
| — | F-6 | Suppress Subprocess Stderr Warnings | S | Flash | ✅ Done | Feedback #6 |
| — | F-7 | Interval Checkpointing | S | Flash | ✅ Done | Feedback #7 |
| — | F-8 | OCR DPI Mismatch | S | Flash | ✅ Done | Feedback #8 |
| — | F-11 | Auto-Scroll PDF Viewer to Focus | S | Flash | 🔀 → Wave 1 (UX) | Feedback #11 |
| **1** | **W1-UX** | **Touch-First UX + Viewer Scroll Focus** | **M** | **Flash** | ✅ Done | Plan Phase 0 + Feedback #11 |
| **1** | **W1-COORD** | **Coordinate Mapping for Scans/Rotation** | **M** | **Flash** | ✅ Done | Feedback #10 |
| **1** | **W1-OVERLAP** | **PDF Annotation Overlap Mitigation** | **M** | **Flash** | ✅ Done | Feedback #9 |
| **1** | **W1-MATRIX** | **Reviewed State in Matrix View** | **M** | **Flash** | ✅ Done | Feedback #12 |
| **2** | W2-GOLDEN | Golden-Output Integration Test | M | Flash | ✅ Done | Plan Phase 2 |
| **2** | W2-ORCH | Orchestrator Decomposition | L | Pro | ✅ Done | Plan Phase 3 |
| **2** | W2-ZIP | Exclude Metadata in ZIP Import | S | Flash | ✅ Done | Feedback #4 |
| **2** | W2-TTY | TTY Bypass for CLI Wizards | S | Flash | ✅ Done | Feedback #2 |
| **3** | W3-CLI | Workflow CLI Decomposition | L | Pro | ✅ Done | Plan Phase 4 |
| **3** | W3-CI | GitHub Actions CI | M | Flash | ✅ Done | Plan Phase 5 |
| **3** | W3-HOUSE | Housekeeping (context.md, docs/) | S | Flash | ✅ Done | Plan Phase 6 |
| **4** | W4-UPLOAD | Browser File Upload & Profile Setup | L | Pro | ✅ Done | Plan Phase 7 |
| **4** | W4-EXPORT | Export Feedback & Browser Download | M | Flash | ✅ Done | Plan Phase 10 + Feedback #13 |
| **4** | W4-COST | LLM Cost Breakdown Dashboard | M | Flash | ✅ Done | Feedback #14 |
| **4** | W4-WORK | Regex Pre-Check `requires_work` Flag | S | Flash | ✅ Done | Feedback #17 |
| **4** | W4-JUDGE | Judge LLM Rounding Error & Partial Credit Audit | S | Flash | ✅ Done | Feedback #20 |
| **5** | W5-SSE | Server Grading + SSE Progress | L | Pro | ✅ Done | Plan Phase 8 |
| **5** | W5-ANNOT | PDF Annotation Editing (Option C) | L | Pro | ✅ Done | Plan Phase 9 |
| **6** | W6-VISION | Force Vision Extraction for Math | S | Flash | ✅ Done | Feedback #18 |
| **6** | W6-CRITERIA | Structured Scoring Criteria Schema | M | Flash | ✅ Done | Feedback #19 |
| **7** | W7-PROMPT | Rubric Gen Prompt v2 (Multi-Method & Decomposition) | S | Flash | ✅ Done | Feedback #21 |
| **7** | W7-NUMERIC | Numeric Answer DSL (`expected_numeric`) | M | Flash | ✅ Done | Feedback #22 |
| **8** | W8-CHECK | Pre-flight Rubric & Data Audit (`./gradeline check`) | S | Flash | Planned | Feedback Reflection |
| **8** | W8-PROFILE | One-Command Profile Auto-Creation | S | Flash | Planned | Feedback Reflection |
| **8** | W8-IMPORT | Smart Import & Solution/Roster Auto-Discovery | M | Flash | Planned | Feedback Reflection |
| **8** | W8-STREAM | Real-time Structured Event Stream (`status.json`) | M | Flash | Planned | Feedback Reflection |
| **8** | **W8-AUDIT** | **PDF Annotation Engine Overhaul & `./gradeline audit-pdf`** | **M** | **Flash** | ✅ Done | Feedback #9, #10, #16 |
| **8** | **W8-SCAN-ANCHOR** | **Scanned PDF OCR Anchor Lookup & Margin Alignment** | **M** | **Flash** | ✅ Done | Feedback #23 |
| **9** | **W9-ANNOT-STATE** | **Extract AnnotationSession Dataclass `[Track A1]`** | **S** | **Flash** | ✅ Done | Feedback #24 |
| **9** | **W9-ANNOT-RENDERER** | **Extract PDF Renderer Module `[Track A2]`** | **M** | **Flash** | ✅ Done | Feedback #24 |
| **9** | **W9-ANNOT-RESOLVER** | **Extract Location Resolver Module `[Track A3]`** | **M** | **Flash** | ✅ Done | Feedback #24 |
| **9** | **W9-ANNOT-PIPELINE** | **Refactor Annotator Pipeline `[Track A4 - Final]`** | **M** | **Flash** | ✅ Done | Feedback #24 |
| **9** | **W9-GEMINI-SCHEMAS** | **Extract Gemini Schemas & Prompts `[Track B1]`** | **S** | **Flash** | ✅ Done | Feedback #24 |
| **9** | **W9-GEMINI-NORMALIZE** | **Extract Response Normalization `[Track B2]`** | **M** | **Flash** | ✅ Done | Feedback #24 |
| **9** | **W9-GEMINI-RESILIENCE** | **Extract Resilience & Thin Client `[Track B3 - Final]`** | **M** | **Flash** | ✅ Done | Feedback #24 |
| **9** | **W9-ORCH-STAGES** | **Extract Orchestrator Stages `[Track C]`** | **M** | **Flash** | ✅ Done | Feedback #24 |
| **9** | **W9-CLI-COMMANDS** | **Extract Workflow CLI Subcommands `[Track D]`** | **M** | **Flash** | ✅ Done | Feedback #24 |
| **10** | **W10-SCAN-DETECT** | **Scanned PDF Quality Classification** | **S** | **Flash** | ✅ Done | HW3 Student A |
| **10** | **W10-COORDS-FIRST** | **Coords-Primary Placement for Scanned PDFs** | **M** | **Flash** | ✅ Done | HW3 Student A |
| **10** | **W10-AUDIT-SPATIAL** | **Enhanced Zero-Token Audit Diagnostics** | **S** | **Flash** | ✅ Done | HW3 Student A |
| **10** | **W10-PROPORTIONAL-FALLBACK**| **Even-Spacing Grid for Missing Coords** | **S** | **Flash** | ✅ Done | HW3 Student A |
| **11** | **W11-NONPDF** | **Non-PDF Submission Ingestion Engine (Images, Excel, Word → PDF)** | **M** | **Flash** | ✅ Done | HW3 Bella Submission |
| **12** | **W12-PROFILE** | **Fix HW4 Profile Config (`hw4.toml`)** | **S** | **Flash** | Planned | HW4 Post-Mortem |
| **12** | **W12-CRITERIA** | **Fix `compute_criteria_partial_score` Regex** | **S** | **Flash** | Planned | HW4 Post-Mortem |
| **12** | **W12-DETECT** | **Validate Snapshot Grade Column in `workflow_detect.py`** | **S** | **Flash** | Planned | HW4 Post-Mortem |
| **12** | **W12-TESTS** | **Add Criteria Parser Test Cases for LLM Phrasing Variants** | **S** | **Flash** | Planned | HW4 Post-Mortem |
| **Backlog** | BL-SEC | App Hardening & Security Auditing | M | Flash | ✅ Done | Security Audit |

| **Backlog** | BL-DOCX | Word/TXT Solutions Keys Support | M | Flash | Backlog | Feedback #1 |
| **Backlog** | BL-SEARCH | Smart Candidate Search in Downloads | S | Flash | Backlog | Feedback #3 |

---

## Wave 6 — Extraction Quality & Rubric Precision

These tasks improve grading accuracy for math-heavy and complex-rubric assignments. No architectural prerequisites — both are opt-in features that leave default behavior unchanged. (Both W6-VISION and W6-CRITERIA have been shipped; prompt details are archived in [shipped-waves-archive.md](archive/shipped-waves-archive.md)).

---

## Wave 7 — Auto-Rubric Generation & Precision

These tasks enhance the AI rubric generation pipeline and simplify rubric authoring based on empirical grading reflection. (Both W7-PROMPT and W7-NUMERIC have been shipped; prompt details are archived in [shipped-waves-archive.md](archive/shipped-waves-archive.md)).

---

## Wave 8 — Workflow, CLI Streamlining & Annotation Reliability

These tasks eliminate manual setup friction, prevent invalid pipeline runs, provide real-time observability, and eliminate PDF visual annotation defects across student outputs.

### Task Prompt: W8-CHECK — Pre-flight Rubric & Data Audit (`./gradeline check`)
Add a zero-token CLI subcommand `./gradeline check --profile <profile>` that validates:
- Rubric YAML fields (`anchor_tokens`, `expected_answers`, non-empty `short_note_fail` for all questions per Feedback Integrity rule).
- Regex syntax compilation for `expected_answers` and `expected_numeric`.
- Points math consistency across questions.
- PDF file presence and basic header readability for all students in roster.

### Task Prompt: W8-PROFILE — One-Command Profile Auto-Creation
Expand profile resolution in `profile_utils.py` and `quickstart.py` to auto-emit `.manual_runs/profiles/<profile>.toml` pre-populated with standard defaults whenever a profile TOML is missing during `import` or `quickstart`. Inherits `DEFAULT_MODEL` per Config Hierarchy rule.

### Task Prompt: W8-IMPORT — Smart Import & Solution/Roster Auto-Discovery
Expand `grader/workflow/import_cmd.py` to:
- Perform fuzzy candidate search for assignment solution PDFs (`<ASSIGNMENT>*.pdf`) in `./data/` or `~/Downloads` and auto-link as `solutions.pdf` with explicit logging.
- Auto-synthesize a valid `grades.csv` adhering to Brightspace export format (`OrgDefinedId`, `Username`, `End-of-Line Indicator`) from Brightspace zip folder names (`ID-ID - Name`) or prior run rosters.

### Task Prompt: W8-STREAM — Real-time Structured Event Stream (`status.json`)
Modify `grader/orchestrator.py` to emit an atomic `status.json` file in the run directory (using `status.json.tmp` -> replace) detailing progress counters (`total`, `completed`, `in_progress`, `review_required_count`, `elapsed_seconds`).

---

## Wave 9 — Codebase Modularization & Refactoring

These tasks decompose high-complexity monoliths (`annotate.py`, `gemini_client.py`, `orchestrator.py`, `workflow_cli.py`) into single-responsibility modules to simplify unit testing, state management, and long-term maintainability.

> [!NOTE]
> **Parallel Execution Matrix**: Tracks A, B, C, and D modify disjoint source files and can be executed **100% in parallel** by separate agents:
> - **Track A (`annotate.py`)**: A1, A2, A3 (leaf extractions in parallel) → A4 (pipeline orchestrator final step)
> - **Track B (`gemini_client.py`)**: B1, B2 (leaf extractions in parallel) → B3 (resilience/client final step)
> - **Track C (`orchestrator.py`)**: C (stages extraction, fully independent)
> - **Track D (`workflow_cli.py`)**: D (CLI subcommands extraction, fully independent)

### Task Prompt: W9-ANNOT-STATE — Extract AnnotationSession Dataclass `[Track A1]` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

### Task Prompt: W9-ANNOT-RENDERER — Extract PDF Renderer Module `[Track A2]` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

### Task Prompt: W9-ANNOT-RESOLVER — Extract Location Resolver Module `[Track A3]` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

### Task Prompt: W9-ANNOT-PIPELINE — Refactor Annotator Pipeline `[Track A4 - Final]` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

### Task Prompt: W9-GEMINI-SCHEMAS — Extract Gemini Schemas & Prompts `[Track B1]` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

### Task Prompt: W9-GEMINI-NORMALIZE — Extract Response Normalization `[Track B2]` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

### Task Prompt: W9-GEMINI-RESILIENCE — Extract Resilience & Thin Client `[Track B3 - Final]` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

### Task Prompt: W9-ORCH-STAGES — Extract Orchestrator Stages `[Track C]` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

### Task Prompt: W9-CLI-COMMANDS — Extract Workflow CLI Subcommands `[Track D]` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

---

## Wave 10 — Handwritten PDF Spatial Anchoring & Audit Quality

These tasks address the root cause of misplaced annotations on scanned handwritten PDFs (like Student A HW3) by shifting from brittle OCR blocks to Gemini's native spatial coordinates, and adding new audit diagnostics to catch spatial clustering defects. (All Wave 10 tasks have been shipped; prompt details are archived in [shipped-waves-archive.md](archive/shipped-waves-archive.md)).

---

## Wave 12 — HW4 Post-Mortem: Criteria Parser & Profile Fixes

These tasks address two bugs discovered during the HW4 grading run:
1. **Brightspace CSV export failed** because `hw4.toml` had a stale `grade_column` from a prior assignment (`"Assignment 2 Points Grade"`) that doesn't exist in `data/hw4/grades.csv`.
2. **Grades were artificially low** because `compute_criteria_partial_score()` in `score.py` used rigid regexes that couldn't parse common LLM `logic_analysis` phrasing. Students meeting 4/5 rubric criteria collapsed to the 0.50 fallback instead of earning 0.80.

> [!NOTE]
> **Root Cause Analysis**: HW4 questions are multi-step process questions (hypothesis tests, confidence intervals with interpretation). The AI rubric generator correctly created `scoring_criteria` checklists and set `requires_work: true`. The `expected_answers` regexes are vestigial hints — the real grading path runs through the LLM + criteria parser. The criteria parser regex is where grades were suppressed.

> [!NOTE]
> **Parallel Execution**: All 4 tasks modify disjoint files and can run **100% in parallel**.

### Task Prompt: W12-PROFILE — Fix HW4 Profile Config (`hw4.toml`)

**File**: `.manual_runs/profiles/hw4.toml`

**Problem**: `grade_column` is set to `"Assignment 2 Points Grade"` (stale from a prior assignment) and `identifier_column` is `"OrgDefinedId"`. The actual CSV headers in `data/hw4/grades.csv` are `"Assignment 4 Points Grade <Numeric MaxPoints:10>"` and `"Username"`.

**Fix**:
1. Open `.manual_runs/profiles/hw4.toml`.
2. Change `grade_column` to `"Assignment 4 Points Grade <Numeric MaxPoints:10>"`.
3. Change `identifier_column` to `"Username"`.
4. Model after `.manual_runs/profiles/hw3.toml` which correctly uses the exact header from `data/hw3/grades.csv`.

**Verification**: Run `.venv/bin/python3 -c 'import csv; r=csv.DictReader(open("data/hw4/grades.csv")); print(r.fieldnames)'` and confirm the `grade_column` value matches a header exactly.

### Task Prompt: W12-CRITERIA — Fix `compute_criteria_partial_score` Regex

**File**: `grader/score.py`, function `compute_criteria_partial_score()` (lines 14–51)

**Problem**: The two regex patterns fail on common LLM `logic_analysis` output styles:
- Pattern 1 `r"(?:criteria|criterion)?\s*([0-9\s,and&]+)\s*met\b"` — fails when auxiliary verbs appear before `met` (e.g. `"Criteria 1, 2, 3, and 4 are met"`) because `are` is not inside the number-capturing group and breaks the match.
- Pattern 2 `r"\b(?:criterion|criteria)\s*(\d+)\s*(?:is|was|[:=])?\s*met\b"` — fails when parenthetical descriptions appear between the number and `met` (e.g. `"Criterion 1 (hypotheses) was met"`) because `(hypotheses)` is not matched by `\s*(?:is|was|[:=])?\s*`.

**Fix** — Replace the two pattern blocks with:
```python
# Pattern 1: List format — "Criteria 1, 2, 3, and 4 [are/were] met"
# Also handles "Criteria 1, 2, 4 met; Criterion 3, 5 unmet"
for match in re.finditer(
    r"(?:criteria|criterion)\s*([0-9\s,and&]+)(?:\([^)]*\))?\s*(?:are|were|is|was|[:=])?\s*met\b",
    logic_analysis,
    flags=re.IGNORECASE,
):
    num_str = match.group(1)
    for num in re.findall(r"\b\d+\b", num_str):
        met_indices.add(int(num))

# Pattern 2: Single item with optional parenthetical description
# e.g. "Criterion 1 (hypotheses) was met" or "Criterion 2 (t-test statistic and df) met"
for match in re.finditer(
    r"\b(?:criterion|criteria)\s*(\d+)\b[^\n.:;]*?\b(?:is|was|are|were)?\s*met\b",
    logic_analysis,
    flags=re.IGNORECASE,
):
    met_indices.add(int(match.group(1)))
```

**Key changes**:
- Pattern 1: Added `(?:are|were|is|was|[:=])?` between the number group and `met`.
- Pattern 2: Changed `\s*(?:is|was|[:=])?\s*` to `[^\n.:;]*?\b(?:is|was|are|were)?\s*` so parenthetical text like `(hypotheses)` is skipped over.

**Verification**:
1. Run `.venv/bin/pytest tests/test_scoring_criteria.py -v` — all existing tests must pass.
2. Manually verify with: `.venv/bin/python3 -c 'from grader.score import compute_criteria_partial_score; from grader.types import ScoringCriterion; c=[ScoringCriterion(requirement="a",weight=1.0) for _ in range(5)]; print(compute_criteria_partial_score("Criteria 1, 2, 3, and 4 are met. Criterion 5 unmet.", c, 0.5))'` — should print `0.8`, not `0.5`.
3. Verify: `.venv/bin/python3 -c 'from grader.score import compute_criteria_partial_score; from grader.types import ScoringCriterion; c=[ScoringCriterion(requirement="a",weight=1.0) for _ in range(5)]; print(compute_criteria_partial_score("Criterion 1 (hypotheses) was met. Criterion 2 (t-test) met. Criterion 3 (comparison) met. Criterion 4 (decision) met. Criterion 5 (assumption) unmet.", c, 0.5))'` — should print `0.8`, not `0.5`.

### Task Prompt: W12-DETECT — Validate Snapshot Grade Column in `workflow_detect.py`

**File**: `grader/workflow_detect.py`, function `detect_defaults()` (around lines 225–254)

**Problem**: When a prior run's `grading_diagnostics.json` snapshot contains a `grade_column` value (e.g. `"Assignment 2 Points Grade"` from a different assignment), `detect_defaults()` trusts it at 85% confidence even when it doesn't match any header in the *current* template CSV. This caused the HW4 run to use a stale column name.

**Fix**: After resolving `grade_column_requested` from the snapshot (line 225) and before the `if grade_column_requested:` check (line 237), add a validation step:
```python
# Validate snapshot grade_column against actual CSV headers
if grade_column_requested and grade_column_source == "recent_run":
    csv_headers = _grade_column_candidates_for_detected_csv(
        grades_template_csv.value, assignment_token=assignment_token
    )
    all_headers = _read_csv_headers(grades_template_csv.value) if grades_template_csv.value else []
    if all_headers and grade_column_requested not in all_headers:
        # Snapshot column doesn't exist in current CSV — discard it
        grade_column_requested = None
```

**Verification**: Run `.venv/bin/pytest tests/test_workflow_detect.py -v` — all existing tests must pass.

### Task Prompt: W12-TESTS — Add Criteria Parser Test Cases for LLM Phrasing Variants

**File**: `tests/test_scoring_criteria.py`

**Problem**: The existing test suite for `compute_criteria_partial_score` only covers basic patterns (`"Criteria 1, 2 met"`, `"Criterion 3 met."`). It does not cover the phrasing variants that real LLM outputs produce.

**Fix**: Add these test methods to class `ScoringCriteriaTests`:

```python
def test_criteria_with_parenthetical_descriptions(self) -> None:
    """Criterion N (description) met/was met patterns are parsed correctly."""
    criteria = [
        ScoringCriterion(requirement="A", weight=1.0),
        ScoringCriterion(requirement="B", weight=1.0),
        ScoringCriterion(requirement="C", weight=1.0),
        ScoringCriterion(requirement="D", weight=1.0),
        ScoringCriterion(requirement="E", weight=1.0),
    ]
    logic = (
        "Criterion 1 (hypotheses) met: Student stated H0. "
        "Criterion 2 (t-test statistic and df) met: Correct. "
        "Criterion 3 (comparison) met: Right. "
        "Criterion 4 (decision) met: Fail to reject. "
        "Criterion 5 (assumption) unmet: Missing normality."
    )
    score = compute_criteria_partial_score(logic, criteria, fallback=0.5)
    self.assertAlmostEqual(score, 0.8)  # 4/5

def test_criteria_list_with_auxiliary_verbs(self) -> None:
    """'Criteria 1, 2, 3, and 4 are met' patterns are parsed correctly."""
    criteria = [
        ScoringCriterion(requirement="A", weight=1.0),
        ScoringCriterion(requirement="B", weight=1.0),
        ScoringCriterion(requirement="C", weight=1.0),
        ScoringCriterion(requirement="D", weight=1.0),
        ScoringCriterion(requirement="E", weight=1.0),
    ]
    logic = "Criteria 1, 2, 3, and 4 are met. Criterion 5 is unmet."
    score = compute_criteria_partial_score(logic, criteria, fallback=0.5)
    self.assertAlmostEqual(score, 0.8)  # 4/5

def test_criteria_was_met_phrasing(self) -> None:
    """'Criterion N (desc) was met' phrasing is parsed correctly."""
    criteria = [
        ScoringCriterion(requirement="A", weight=1.0),
        ScoringCriterion(requirement="B", weight=2.0),
    ]
    logic = "Criterion 1 (standard error) was met by calculating SE correctly. Criterion 2 (interval) was unmet."
    score = compute_criteria_partial_score(logic, criteria, fallback=0.5)
    self.assertAlmostEqual(score, 1.0 / 3.0)  # weight 1.0 / total 3.0

def test_criteria_semicolon_separated_mixed(self) -> None:
    """'Criteria 1, 2, 4 met; Criterion 3, 5 unmet' mixed format."""
    criteria = [
        ScoringCriterion(requirement="A", weight=1.0),
        ScoringCriterion(requirement="B", weight=1.0),
        ScoringCriterion(requirement="C", weight=1.0),
        ScoringCriterion(requirement="D", weight=1.0),
        ScoringCriterion(requirement="E", weight=1.0),
    ]
    logic = "Criteria 1, 2, 4 met; Criterion 3, 5 unmet."
    score = compute_criteria_partial_score(logic, criteria, fallback=0.5)
    self.assertAlmostEqual(score, 0.6)  # 3/5
```

**Verification**: Run `.venv/bin/pytest tests/test_scoring_criteria.py -v` — all new and existing tests must pass (requires W12-CRITERIA to be applied first, or tests will demonstrate the bug).

---

## Backlog

| Task ID | Title | Size | Notes |
|:---:|:---|:---:|:---|
| BL-SEC | App Hardening & Security Auditing | M | Automated static analysis (`bandit`, `pip-audit`), strict path traversal guards, and untrusted data prompt isolation. |
| BL-DOCX | Word/TXT/MD Solutions Keys Support | M | Lower friction for instructors. (Note: Student submission DOCX conversion already exists in `discovery.py`; this task is specifically for converting/parsing solution keys). |
| BL-SEARCH | Smart Candidate Search in Downloads | S | Sort by modified date, weight profile name matches higher. |
| BL-SAVED-ANIM | Autosave Micro-Animations & Visual Confirmation | S | Disappearing popups, subtle green pulse ring, and "Saved ✓" badges on patches in Review UI. |
| BL-WEB-WORKSTATION | Unified Web-Based Grading Workstation | XL | Single intuitive web app for non-tech professors covering Ingestion, Auto-Rubric Creation, Grading, and Review. |
| BL-CRITERIA-STRUCT | Structured `criteria_met` in LLM Response Schema | M | Add `criteria_met: list[int]` to `UnifiedQuestionItem` so the LLM returns which scoring criteria indices were satisfied as machine-readable data instead of free-text prose parsed by regex. Eliminates fragility of `compute_criteria_partial_score()` regex parsing across all subjects/languages. Requires schema change in `gemini_schemas.py`, fallback logic in `score.py`, and prompt update in `gemini_schemas.py` context instructions. |


