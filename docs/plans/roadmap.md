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
| **9** | W9-ANNOT-STATE | Extract AnnotationSession Dataclass | S | Flash | Planned | Feedback #24 |
| **9** | W9-ANNOT-RENDERER | Extract PDF Renderer Module | M | Flash | Planned | Feedback #24 |
| **9** | W9-ANNOT-RESOLVER | Extract Location Resolver Module | M | Flash | Planned | Feedback #24 |
| **9** | W9-ANNOT-PIPELINE | Refactor Annotator Pipeline | M | Flash | Planned | Feedback #24 |
| **9** | W9-GEMINI-SCHEMAS | Extract Gemini Schemas & Prompts | S | Flash | Planned | Feedback #24 |
| **9** | W9-GEMINI-NORMALIZE | Extract Response Normalization | M | Flash | Planned | Feedback #24 |
| **9** | W9-GEMINI-RESILIENCE | Extract Resilience & Thin Client | M | Flash | Planned | Feedback #24 |
| **9** | W9-ORCH-STAGES | Extract Orchestrator Stages | M | Flash | Planned | Feedback #24 |
| **9** | W9-CLI-COMMANDS | Extract Workflow CLI Subcommands | M | Flash | Planned | Feedback #24 |
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

### Task Prompt: W9-ANNOT-STATE — Extract AnnotationSession Dataclass
Modify `grader/annotate.py` to extract the tracking dictionaries and sets (`placed_rects`, `rendered`, `rendered_subparts`, `placement_details`) from `annotate_submission_pdfs` into a cohesive `AnnotationSession` dataclass. Update the existing functions to use this new state object.

### Task Prompt: W9-ANNOT-RENDERER — Extract PDF Renderer Module
Extract drawing and PyMuPDF operations from `grader/annotate.py` into a new `grader/pdf_renderer.py` module. This should include `insert_mark`, `add_movable_freetext_annotation`, `find_non_overlapping_rect`, `is_dark_background`, and related constants. Update `annotate.py` to import from this new module.

### Task Prompt: W9-ANNOT-RESOLVER — Extract Location Resolver Module
Extract pure placement strategy functions from `grader/annotate.py` into a new `grader/location_resolver.py` module. This includes `resolve_model_location`, `find_anchor_in_doc`, OCR block heuristics, token matching, and `clean_subpart_label()`. Aim for minimal `fitz` dependency where possible to enable fast unit testing. Update `annotate.py` to import from this new module.

### Task Prompt: W9-ANNOT-PIPELINE — Refactor Annotator Pipeline
Refactor the high-level `annotate_submission_pdfs` function in `grader/annotate.py` (now acting as the orchestrator) into smaller pipeline helpers like `_annotate_single_pdf` and `_append_unresolved_summary`. Ensure the module cleanly stitches together `AnnotationSession`, `location_resolver`, and `pdf_renderer`. Ensure existing public function signatures remain the same.

### Task Prompt: W9-GEMINI-SCHEMAS — Extract Gemini Schemas & Prompts
Extract Pydantic models, JSON schema definitions, and prompt builder functions from `grader/gemini_client.py` into a new `grader/gemini_schemas.py` module. This creates a pure data contract boundary with zero API dependency.

### Task Prompt: W9-GEMINI-NORMALIZE — Extract Response Normalization
Extract all response parsing, derivation, and normalization logic (e.g., `normalize_model_response`, `normalize_locator_response`) from `grader/gemini_client.py` into a new `grader/gemini_normalize.py` module.

### Task Prompt: W9-GEMINI-RESILIENCE — Extract Resilience & Thin Client
Extract rate limiting, caching, exponential backoff retries, and error mapping logic from `grader/gemini_client.py` into a new `grader/gemini_resilience.py` module. Leave a clean, lightweight transport API client (`GeminiGrader`) in `gemini_client.py` that stitches together schemas, normalization, and resilience logic.

### Task Prompt: W9-ORCH-STAGES — Extract Orchestrator Stages
Decompose the monolithic `grader/orchestrator.py` (1,184 lines) by extracting pipeline phases (e.g., precheck, grading, annotation) into dedicated stage handler sub-modules under `grader/stages/`. The `Orchestrator` class should remain as a thin coordinator.

### Task Prompt: W9-CLI-COMMANDS — Extract Workflow CLI Subcommands
Decompose the monolithic `grader/workflow_cli.py` (1,206 lines) by extracting subcommand handlers (e.g., `run_from_profile`, `regrade_from_profile`) into dedicated modules under `grader/workflow/commands/`. The `main()` dispatch function and `build_parser()` should remain in `workflow_cli.py`.

---

## Backlog

| Task ID | Title | Size | Notes |
|:---:|:---|:---:|:---|
| BL-SEC | App Hardening & Security Auditing | M | Automated static analysis (`bandit`, `pip-audit`), strict path traversal guards, and untrusted data prompt isolation. |
| BL-DOCX | Word/TXT/MD Solutions Keys Support | M | Lower friction for instructors. (Note: Student submission DOCX conversion already exists in `discovery.py`; this task is specifically for converting/parsing solution keys). |
| BL-SEARCH | Smart Candidate Search in Downloads | S | Sort by modified date, weight profile name matches higher. |
| BL-VISION-AUTO | Auto-Detect Math-Heavy Pages | M | Heuristic to detect Tesseract gibberish on math content and selectively re-extract via Gemini. Follow-up to W6-VISION — the flag becomes a hard override, the heuristic becomes the smart default. |
| BL-SAVED-ANIM | Autosave Micro-Animations & Visual Confirmation | S | Disappearing popups, subtle green pulse ring, and "Saved ✓" badges on patches in Review UI. |
| BL-WEB-WORKSTATION | Unified Web-Based Grading Workstation | XL | Single intuitive web app for non-tech professors covering Ingestion, Auto-Rubric Creation, Grading, and Review. |

