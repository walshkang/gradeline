# Gradeline — Project Context

## Completed
- **Delegation Prompts Refactoring**: Completed Phase 1 (Cleanup), Phase 2 (Feedback Integrity), Phase 3 (Hybrid Regex Engine & Audit Trail). See [archive/refactor-delegation-prompts.md](docs/plans/archive/refactor-delegation-prompts.md) for historical details.
- **End-State Architecture Refactoring**: Completed Slice 1 (State Decoupling), Slice 2 (Orchestrator Refactor), and Slice 3 (Zero-Trust Boundaries). See [archive/architecture-endstate.md](docs/plans/archive/architecture-endstate.md) for historical details.
- **Trust Loop & Visual Audit**: Completed Phase 1 to Phase 5. See [archive/trust-loop-and-visual-audit.md](docs/plans/archive/trust-loop-and-visual-audit.md) for historical details.
- **Review Server UX Improvements**: Completed automated E2E integration testing with Playwright browser testing and local mirror fallbacks. See [archive/review-server-ux-improvements.md](docs/plans/archive/review-server-ux-improvements.md) for historical details.
- **Stability, Decomposition & Browser-First Grading (Waves 1–5 Shipped)**: 
  - Completed Wave 1 (Touch-First UX split-screen, Coordinate Mapping for scans/rotation, PDF Annotation Overlap mitigation, and Reviewed State indicators in Matrix View).
  - Completed Wave 2 (Golden-Output integration testing, stateless Orchestrator modularization into `grading.py`/`preprocessing.py`, D2L metadata ZIP import exclusion, and CLI interactive bypass).
  - Completed Wave 3 (Workflow CLI decomposition into `grader/workflow/`, GitHub Actions CI pipeline, and documentation housekeeping).
  - Completed Wave 4 (Browser File Upload & Profile Setup, Export Feedback & Download, LLM Cost Breakdown Dashboard, Regex Pre-Check `requires_work` flag, and Judge LLM Rounding Error/Partial Credit Audit).
  - Completed Wave 5 (Server Grading with SSE live progress in `grading_session.py`, Sidebar PDF Annotation Editing with multi-marker overlays).
- **Auto-Rubric Generation & Precision (Wave 7 Shipped)**:
  - Completed W7-PROMPT (Rubric Gen Prompt v2 for multi-method variation expansion and atomic sub-question decomposition + string path support in `load_rubric`).
- **Review Server & Audit Justification Fix**:
  - Resolved missing justifications (`logic_analysis`, `short_reason`, `detail_reason`) and missing suggested grades/verdicts for `needs_review` questions across primary model response normalization, fallback error handling, audit CSV generation, review state import, and review server UI rendering (including a new Suggested Grade & Rationale banner with 1-click apply).
- **Workflow, CLI Streamlining & Annotation Reliability (Wave 8 Progress)**:
  - Completed `W8-AUDIT` (PDF Visual Annotation Engine Overhaul & Zero-Token `./gradeline audit-pdf` Diagnostic Suite). Fixed OOB bleeding, page 1 summary note overlap, scanned PDF text density anchors, and subpart resolution tracking across 292 student output PDFs.
  - Completed `W8-SCAN-ANCHOR` (Scanned PDF OCR Anchor Lookup & Left Margin Alignment). Integrated Gemini Flash OCR `block_registry` fallback search in `find_anchor_in_doc`, region-bounded sub-question marker re-anchoring, left-margin badge alignment (`x = block.left - margin`), and refined LLM `block_id` starting line rules. Tested & verified against scanned assignments (Aaron Gurley, Aldo Arossa).
- **Detailed prompt specifications for shipped waves are archived in [archive/shipped-waves-archive.md](docs/plans/archive/shipped-waves-archive.md).**

## Current Objective
Active objective is completing remaining **Wave 8 — Workflow & CLI Streamlining** tasks in the [Gradeline Unified Roadmap](docs/plans/roadmap.md):
- `W8-CHECK`: Pre-flight Rubric & Data Audit (`./gradeline check`)
- `W8-PROFILE`: One-Command Profile Auto-Creation
- `W8-IMPORT`: Smart Import & Solution/Roster Auto-Discovery
- `W8-STREAM`: Real-time Structured Event Stream (`status.json`)

## Next Strategic Direction (Professor Web Workstation & UX)
- **Intuitive Web App for Non-Tech Professors**: Building out the Review Server into a self-describing workstation with opt-in instructions and unobtrusive autosave visual feedback (`BL-SAVED-ANIM`).
- **Unified Web Workstation Vision (`BL-WEB-WORKSTATION`)**: Expanding the web interface to eventually cover assignment ingestion and auto-rubric creation, giving non-tech professors a single browser workstation for the entire assignment grading lifecycle.
