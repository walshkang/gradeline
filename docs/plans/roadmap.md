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
| **10** | **W10-SCAN-DETECT** | **Scanned PDF Quality Classification** | **S** | **Flash** | Planned | HW3 Student A |
| **10** | **W10-COORDS-FIRST** | **Coords-Primary Placement for Scanned PDFs** | **M** | **Flash** | Planned | HW3 Student A |
| **10** | **W10-AUDIT-SPATIAL** | **Enhanced Zero-Token Audit Diagnostics** | **S** | **Flash** | Planned | HW3 Student A |
| **10** | **W10-PROPORTIONAL-FALLBACK**| **Even-Spacing Grid for Missing Coords** | **S** | **Flash** | Planned | HW3 Student A |
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

These tasks address the root cause of misplaced annotations on scanned handwritten PDFs (like Student A HW3) by shifting from brittle OCR blocks to Gemini's native spatial coordinates, and adding new audit diagnostics to catch spatial clustering defects.

### Task Prompt: W10-SCAN-DETECT — Scanned PDF Quality Classification
- In `extract.py`, add `_is_gibberish_blocks(blocks)` heuristic to flag low-quality Tesseract blocks (e.g., mean word length < 2.5, blocks covering > 35% of page).
- Modify `_needs_gemini_fallback()` to return `True` on gibberish.
- Add `quality: str = "unknown"` field to `ExtractedPdf` dataclass to track extraction confidence (`native`, `ocr_clean`, `ocr_low`).
- **Resolution**: Continue using `_needs_gemini_fallback` to trigger Gemini OCR for better text (for regex pre-checks), but mark those Gemini OCR blocks as `quality="ocr_low"` so they aren't used for spatial anchoring on handwriting.

### Task Prompt: W10-COORDS-FIRST — Coords-Primary Placement for Scanned PDFs
- In `grading.py`, do not pass `blocks=` to `grade_submission_unified()` if `ExtractedPdf.quality == "ocr_low"`. This forces Gemini to use native `coords=[y,x]` for placement instead of referencing garbage `<answer id="p3_b3">` blocks.
- In `gemini_schemas.py`, add the clarification: *"If no `<answer>` blocks are provided in the prompt, you MUST set `coords=[y,x]` for each question."* (Keep the existing `block_id` override rule for digital PDFs).
- In `location_resolver.py`, when a resolved `block_id` points to a mega-block covering >30% of the page area, reject it and fall back to coords.
- Keep `block_registry` for the annotation stage so anchor text search fallback still works if needed.

### Task Prompt: W10-AUDIT-SPATIAL — Enhanced Zero-Token Audit Diagnostics
- In `audit_pdf.py`, add 3 new geometric checks to `audit_pdf_outputs()`:
  1. **Top-Margin Clustering**: Flag pages where ≥3 annotations have `y0 < page_height * 0.15`.
  2. **Oversized Anchor Box**: Flag annotations whose matched block bounding box is disproportionately large (e.g. height > 80pt or width > 300pt for a simple `✓ Q3a` mark).
  3. **Same-Y Clustering**: Flag pages where ≥3 annotations share the same y-coordinate (±5pt), indicating they all mapped to a single mega-block.

### Task Prompt: W10-PROPORTIONAL-FALLBACK — Even-Spacing Grid for Missing Coords
- In `location_resolver.py`, add a `proportional_page_fallback(page, question_index, total_questions)` function.
- If both `block_id` and `coords` are missing/rejected for a scanned PDF, space the annotations evenly down the left margin instead of dropping them.

---

## Backlog

| Task ID | Title | Size | Notes |
|:---:|:---|:---:|:---|
| BL-SEC | App Hardening & Security Auditing | M | Automated static analysis (`bandit`, `pip-audit`), strict path traversal guards, and untrusted data prompt isolation. |
| BL-DOCX | Word/TXT/MD Solutions Keys Support | M | Lower friction for instructors. (Note: Student submission DOCX conversion already exists in `discovery.py`; this task is specifically for converting/parsing solution keys). |
| BL-SEARCH | Smart Candidate Search in Downloads | S | Sort by modified date, weight profile name matches higher. |
| BL-SAVED-ANIM | Autosave Micro-Animations & Visual Confirmation | S | Disappearing popups, subtle green pulse ring, and "Saved ✓" badges on patches in Review UI. |
| BL-WEB-WORKSTATION | Unified Web-Based Grading Workstation | XL | Single intuitive web app for non-tech professors covering Ingestion, Auto-Rubric Creation, Grading, and Review. |


