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
| **12** | **W12-PROFILE** | **Fix HW4 Profile Config (`hw4.toml`)** | **S** | **Flash** | ✅ Done | HW4 Post-Mortem |
| **12** | **W12-CRITERIA** | **Fix `compute_criteria_partial_score` Regex** | **S** | **Flash** | ✅ Done | HW4 Post-Mortem |
| **12** | **W12-DETECT** | **Validate Snapshot Grade Column in `workflow_detect.py`** | **S** | **Flash** | ✅ Done | HW4 Post-Mortem |
| **12** | **W12-TESTS** | **Add Criteria Parser Test Cases for LLM Phrasing Variants** | **S** | **Flash** | ✅ Done | HW4 Post-Mortem |
| **Backlog** | BL-SEC | App Hardening & Security Auditing | M | Flash | ✅ Done | Security Audit |
| **13** | **W13-SHELL** | **Workstation Navigation Shell & Landing Page** | **M** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **13** | **W13-ASSIGNMENTS** | **Assignment Switcher & Run History** | **M** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **13** | **W13-LAUNCH** | **Standalone Workstation Launch Mode** | **S** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **13** | **W13-WIZARD** | **Guided Setup Wizard (Step-by-Step)** | **M** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **14** | **W14-RUBRIC-EDITOR** | **In-Browser Rubric YAML Editor** | **M** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **14** | **W14-DASHBOARD** | **Grading Run Dashboard & Analytics** | **M** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **14** | **W14-PROGRESS** | **Enhanced Grading Progress View** | **S** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **14** | **W14-TOAST** | **Autosave Micro-Animations & Visual Confirmation** | **S** | **Flash** | Planned | BL-WEB-WORKSTATION + BL-SAVED-ANIM |
| **15** | **W15-DESIGN** | **Design System & Visual Overhaul** | **L** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **15** | **W15-RESPONSIVE** | **Tablet & Mobile Responsive Layout** | **M** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **15** | **W15-HELP** | **Contextual Help & Onboarding Tooltips** | **S** | **Flash** | Planned | BL-WEB-WORKSTATION |
| **15** | **W15-EXPORT-UX** | **Export Workflow Polish** | **S** | **Flash** | Planned | BL-WEB-WORKSTATION |

| **Backlog** | BL-DOCX | Word/TXT Solutions Keys Support | M | Flash | Backlog | Feedback #1 |
| **Backlog** | BL-SEARCH | Smart Candidate Search in Downloads | S | Flash | Backlog | Feedback #3 |
| **Backlog** | BL-RUBRIC-AI | AI Meta-Prompting for Subject-Aware Rubric Generation | M | Pro | Backlog | Pre-Flight Checks |

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

### Task Prompt: W12-PROFILE — Fix HW4 Profile Config (`hw4.toml`) ✅ Done

**File**: `.manual_runs/profiles/hw4.toml`

**Problem**: `grade_column` is set to `"Assignment 2 Points Grade"` (stale from a prior assignment) and `identifier_column` is `"OrgDefinedId"`. The actual CSV headers in `data/hw4/grades.csv` are `"Assignment 4 Points Grade <Numeric MaxPoints:10>"` and `"Username"`.

**Fix**:
1. Open `.manual_runs/profiles/hw4.toml`.
2. Change `grade_column` to `"Assignment 4 Points Grade <Numeric MaxPoints:10>"`.
3. Change `identifier_column` to `"Username"`.
4. Model after `.manual_runs/profiles/hw3.toml` which correctly uses the exact header from `data/hw3/grades.csv`.

**Verification**: Run `.venv/bin/python3 -c 'import csv; r=csv.DictReader(open("data/hw4/grades.csv")); print(r.fieldnames)'` and confirm the `grade_column` value matches a header exactly.

### Task Prompt: W12-CRITERIA — Fix `compute_criteria_partial_score` Regex ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*


### Task Prompt: W12-DETECT — Validate Snapshot Grade Column in `workflow_detect.py` ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*

### Task Prompt: W12-TESTS — Add Criteria Parser Test Cases for LLM Phrasing Variants ✅ Done
*(Task shipped — prompt archived in `docs/plans/archive/shipped-waves-archive.md`)*


---

## Wave 13 — Workstation Shell & Assignment Hub (Foundation)

These tasks transform the existing review web app into a full grading workstation by adding a navigation shell, multi-assignment management, and a guided setup wizard for non-tech professors.

> [!NOTE]
> **Architecture decisions**: Multi-instance `ReviewApi` with lazy initialization for assignment switching. Vanilla JS with ES modules (`import`/`export`) to decompose `app.js` — no framework migration.

> [!NOTE]
> **Execution order**: W13-SHELL is the foundation — W13-ASSIGNMENTS, W13-WIZARD, and W13-LAUNCH can run in parallel after the shell ships.

### Task Prompt: W13-SHELL — Workstation Navigation Shell & Landing Page

**Files to modify**: `grader/review/static/index.html`, `grader/review/static/styles.css`, `grader/review/static/app.js`

**Goal**: Replace the flat top-bar tab group (Review / Config / Matrix / Setup) with a proper sidebar navigation shell:
1. Add a fixed left sidebar (~220px) with icon+label nav items: Dashboard, Setup, Grade, Review, Matrix, Config, Export.
2. The main content area renders the active view. All existing tab panels become views within this shell.
3. Add a **Dashboard** landing page as the default view showing: current profile name, grading run status (idle/completed/in-progress), quick-action cards ("Setup New Assignment", "Resume Review", "Export Results").
4. The sidebar should highlight the active view and collapse to icons-only on narrow viewports (<900px).
5. Preserve all existing tab/panel functionality — this is a layout wrapper, not a rewrite.

**Verification**: Open the review server, confirm all existing tabs still work as views within the new shell. Sidebar highlights correctly on navigation.

### Task Prompt: W13-ASSIGNMENTS — Assignment Switcher & Run History

**Files to modify**: `grader/review/server.py`, `grader/review/api.py`, `grader/review/static/app.js`, `grader/review/static/index.html`

**Goal**: Add API and UI for multi-assignment management:
1. **`GET /api/profiles`**: List all profile TOMLs in `configs/profiles/`, return `[{name, has_output, grading_status, last_run_timestamp}]`. Check for `outputs/<profile>/grading_diagnostics.json` to determine status.
2. **Multi-instance `ReviewApi` registry**: In `server.py`, maintain a `dict[str, ReviewApi]` keyed by profile name. Lazily initialize `ReviewApi` instances when a profile is selected. The active profile is tracked in a server-level variable.
3. **`POST /api/profiles/switch`**: Switch the active profile. Body: `{"profile": "hw3"}`. Initializes `ReviewApi` for the target profile if not already loaded.
4. **UI**: Add a profile selector dropdown in the sidebar header. Switching profiles reloads all data (submissions list, matrix, config) from the newly active profile's output dir.
5. **Standalone mode**: When the server starts without `--output-dir`, default to listing all available profiles instead of erroring.

**Verification**: Start server, switch between profiles via the dropdown. Each profile loads its own submissions, review state, and config.

### Task Prompt: W13-LAUNCH — Standalone Workstation Launch Mode

**Files to modify**: `grader/workflow_cli.py`, `grader/review/server.py`

**Goal**: Add a `workstation` CLI command for standalone launch:
1. Add `workstation` subcommand to the workflow CLI (`interactive_command_menu` and argparse): `./gradeline workstation [--host HOST] [--port PORT]`.
2. Starts the review server in "workstation mode" — no `--output-dir` required. The server discovers all profiles from `configs/profiles/` and lets the user switch between them in the browser.
3. Add `workstation` as a choice in the interactive command menu (positioned after `review`).
4. If no profiles exist, the server opens to the Setup wizard view by default.

**Verification**: Run `./gradeline workstation`, confirm the browser shows the assignment switcher with all available profiles.

### Task Prompt: W13-WIZARD — Guided Setup Wizard (Step-by-Step)

**Files to modify**: `grader/review/static/index.html`, `grader/review/static/styles.css`, `grader/review/static/app.js`

**Goal**: Replace the current flat Setup tab with a multi-step wizard:
1. **Step 1 — Name**: Profile name input with validation (alphanumeric + hyphens).
2. **Step 2 — Upload**: The existing drag-and-drop zones for Submissions ZIP, Solutions PDF, Rubric YAML, Brightspace CSV. Show green checkmarks on successful uploads.
3. **Step 3 — Rubric**: If no rubric was uploaded, offer the "Generate AI Rubric" button. Show a preview of the generated YAML. Allow re-generation.
4. **Step 4 — Configure**: Model selection, concurrency, grade column (from CSV headers), grade point values.
5. **Step 5 — Review & Launch**: Summary of all settings. "Save Profile" and "Save & Start Grading" buttons.
6. Add a horizontal step indicator (Step 1 of 5, Step 2 of 5, ...) with clickable step labels. Back/Next navigation buttons.
7. Validate each step before allowing progression (e.g., profile name required in Step 1, at least submissions ZIP in Step 2).

**Verification**: Walk through all 5 steps, create a profile, confirm it's saved to `configs/profiles/`. The wizard should feel linear and guided.

---

## Wave 14 — Rubric Editor & Grading Dashboard (Intelligence)

These tasks give professors visibility and control over the grading pipeline with a visual rubric editor, post-run analytics, enhanced progress tracking, and autosave micro-animations.

> [!NOTE]
> **BL-SAVED-ANIM absorption**: The backlog item `BL-SAVED-ANIM` is fully absorbed into `W14-TOAST`.

### Task Prompt: W14-RUBRIC-EDITOR — In-Browser Rubric YAML Editor

**Files to modify**: `grader/review/static/index.html`, `grader/review/static/styles.css`, `grader/review/static/app.js`, `grader/review/server.py`

**Goal**: Add a visual rubric editor view:
1. **`GET /api/rubric`**: Load the rubric YAML for the active profile, return parsed JSON.
2. **`PUT /api/rubric`**: Save the edited rubric back as YAML.
3. **Structured view**: Render each question as a card with editable fields: `anchor_tokens`, `expected_answers`, `scoring_criteria` (list), `short_note_fail`, `requires_work`, `expected_numeric`. Sub-questions as nested cards.
4. **Raw YAML toggle**: A toggle to switch between the structured card view and a syntax-highlighted raw YAML editor (using a `<textarea>` with monospace font and basic YAML validation).
5. **Validation**: Warn on empty `short_note_fail` (per Feedback Integrity rule), regex syntax errors in `expected_answers`.

**Verification**: Load a rubric, edit a question's `expected_answers`, save, reload — changes persisted. Toggle between structured and raw views.

### Task Prompt: W14-DASHBOARD — Grading Run Dashboard & Analytics

**Files to modify**: `grader/review/static/index.html`, `grader/review/static/styles.css`, `grader/review/static/app.js`, `grader/review/server.py`, `grader/review/api.py`

**Goal**: Build a post-grading dashboard view (the Dashboard landing page from W13-SHELL, enhanced):
1. **Band distribution chart**: Horizontal bar chart showing count per band (10, 9, Review). Use inline SVG or `<canvas>`.
2. **Per-question accuracy heatmap**: Compact grid showing correct% per question (green → red gradient). Reuse data from `grading_audit.csv`.
3. **Cost breakdown**: Total cost, cost per submission, cost by model. Reuse existing `cost.py` data from `grading_diagnostics.json`.
4. **Timing stats**: Mean/median/max time per submission, total wall-clock time.
5. **Review required count**: Prominent badge showing submissions needing human review.
6. **`GET /api/dashboard`**: New API endpoint aggregating all the above from `grading_diagnostics.json` and `grading_audit.csv`.

**Verification**: Complete a grading run, navigate to Dashboard, verify charts render with correct data.

### Task Prompt: W14-PROGRESS — Enhanced Grading Progress View

**Files to modify**: `grader/review/static/index.html`, `grader/review/static/styles.css`, `grader/review/static/app.js`

**Goal**: Replace the basic progress modal with a richer in-page panel:
1. Replace the `#gradingProgressModal` overlay with an in-page panel in the main content area (within the navigation shell).
2. Show live student-by-student progress cards: student name, band result, elapsed time. Color-code by band.
3. Add estimated time remaining based on mean time per completed submission.
4. Show an expandable error log for any failed submissions.
5. Auto-transition: when grading completes, show a "View Results" button that switches to the Review view and refreshes submissions.

**Verification**: Start a grading run, verify progress cards appear in real-time. On completion, click "View Results" and confirm review view loads the new data.

### Task Prompt: W14-TOAST — Autosave Micro-Animations & Visual Confirmation

**Files to modify**: `grader/review/static/styles.css`, `grader/review/static/app.js`

**Goal**: Add autosave visual feedback throughout the Review UI (absorbs backlog item `BL-SAVED-ANIM`):
1. **Toast notifications**: Slim, disappearing toast popups (bottom-right) on save operations: "Verdict saved", "Note updated", "Grade adjusted". Auto-dismiss after 2s with fade-out.
2. **Pulse animation**: Subtle green pulse ring on the active verdict button when a save succeeds.
3. **Saved badge**: Brief "Saved ✓" text that appears next to patched fields (verdict, confidence, reason) and fades after 1.5s.
4. **Error toast**: Red-tinted toast for failed saves with retry suggestion.
5. All animations should use CSS `@keyframes` — no JS animation libraries.

**Verification**: In Review, change a verdict — verify toast appears, pulse animates, and "Saved ✓" badge shows briefly.

---

## Wave 15 — UX Polish & Premium Design (Premium)

These tasks elevate the visual design, responsiveness, and onboarding experience to a polished, premium product feel.

### Task Prompt: W15-DESIGN — Design System & Visual Overhaul

**Files to modify**: `grader/review/static/styles.css`, `grader/review/static/index.html`

**Goal**: Implement a cohesive design system and restyle the entire workstation:
1. **CSS custom properties**: Define a complete token system (`--color-primary`, `--color-surface`, `--spacing-*`, `--radius-*`, `--font-*`).
2. **Dark mode**: Add a dark mode toggle in the sidebar. Use `prefers-color-scheme` as default, with manual override persisted in `localStorage`.
3. **Typography**: Import Google Fonts (Inter) and apply consistently. Establish heading/body/caption hierarchy.
4. **Component library**: Consistent card, button, input, select, badge, and tooltip styles. Glassmorphism-inspired panels with backdrop blur.
5. **Smooth transitions**: Add `transition` to all interactive elements (buttons, sidebar, panels). Page-view transitions with subtle opacity/slide animations.
6. **Color palette**: Replace generic colors with a curated HSL-based palette (slate/indigo/emerald/amber).

**Verification**: Full visual audit — every view should feel cohesive, modern, and premium. Dark mode toggle should work without flicker.

### Task Prompt: W15-RESPONSIVE — Tablet & Mobile Responsive Layout

**Files to modify**: `grader/review/static/styles.css`, `grader/review/static/app.js`

**Goal**: Ensure the workstation works well on iPad-sized screens (primary professor use case):
1. **Collapsible sidebar**: Below 900px, sidebar collapses to icons-only with a hamburger toggle.
2. **Touch-friendly controls**: Minimum 44px tap targets for all interactive elements.
3. **Adaptive grids**: Config, setup wizard, and matrix grids reflow to single-column on narrow viewports.
4. **PDF viewer**: On tablet, the viewer should take full width with the editor as a bottom sheet (preserve existing split-screen behavior from W1-UX).

**Verification**: Test at iPad viewport (1024×768). All views should be usable without horizontal scrolling.

### Task Prompt: W15-HELP — Contextual Help & Onboarding Tooltips

**Files to modify**: `grader/review/static/index.html`, `grader/review/static/styles.css`, `grader/review/static/app.js`

**Goal**: Add contextual help for non-tech professors:
1. **First-run overlay**: On first visit (check `localStorage`), show a brief onboarding overlay with 3-4 slides explaining the workflow: Upload → Grade → Review → Export.
2. **`?` tooltips**: Add small `?` icons next to key UI elements (verdict buttons, grade points, scoring criteria, band thresholds) that show explanatory tooltips on hover/tap.
3. **Help panel**: Add a "Help" item in the sidebar nav that opens a panel with FAQs and workflow tips.

**Verification**: Clear localStorage, reload — onboarding overlay should appear. Hover over `?` icons to see tooltips.

### Task Prompt: W15-EXPORT-UX — Export Workflow Polish

**Files to modify**: `grader/review/static/index.html`, `grader/review/static/styles.css`, `grader/review/static/app.js`

**Goal**: Add a guided export view (replaces the dropdown menu):
1. **Export view**: A dedicated view in the navigation shell showing all export options as cards: Brightspace CSV, Audit CSV, Reviewed PDFs, Complete Bundle.
2. **Preview**: Show a preview of the Brightspace CSV (first 5 rows) before download.
3. **Download confirmation**: After download, show file size and row count.
4. **Validation**: Warn if there are unreviewed `REVIEW_REQUIRED` submissions before allowing Brightspace CSV export.

**Verification**: Navigate to Export view, preview CSV, download bundle. Verify warnings appear when submissions are unreviewed.

---

## Backlog

| Task ID | Title | Size | Notes |
|:---:|:---|:---:|:---|
| BL-SEC | App Hardening & Security Auditing | M | Automated static analysis (`bandit`, `pip-audit`), strict path traversal guards, and untrusted data prompt isolation. |
| BL-DOCX | Word/TXT/MD Solutions Keys Support | M | Lower friction for instructors. (Note: Student submission DOCX conversion already exists in `discovery.py`; this task is specifically for converting/parsing solution keys). |
| BL-SEARCH | Smart Candidate Search in Downloads | S | Sort by modified date, weight profile name matches higher. |
| BL-CRITERIA-STRUCT | Structured `criteria_met` in LLM Response Schema | M | Add `criteria_met: list[int]` to `UnifiedQuestionItem` so the LLM returns which scoring criteria indices were satisfied as machine-readable data instead of free-text prose parsed by regex. Eliminates fragility of `compute_criteria_partial_score()` regex parsing across all subjects/languages. Requires schema change in `gemini_schemas.py`, fallback logic in `score.py`, and prompt update in `gemini_schemas.py` context instructions. |
