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
  - Completed W7-NUMERIC (Numeric Answer DSL `expected_numeric` for automatic regex compilation of decimal variations, tolerances, and percentages).
  - Detailed prompt specifications for shipped waves are archived in [archive/shipped-waves-archive.md](docs/plans/archive/shipped-waves-archive.md).

## Current Objective
Wave 7 completed and verified! Next active tasks in the [Gradeline Unified Roadmap](docs/plans/roadmap.md) are backlog items (BL-SEC: App Hardening & Security Auditing, BL-DOCX: Word/TXT Solution Keys Support, BL-SEARCH: Smart Candidate Search).


