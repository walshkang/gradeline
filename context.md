# Gradeline — Project Context

## Completed
- **Delegation Prompts Refactoring**: Completed Phase 1 (Cleanup), Phase 2 (Feedback Integrity), Phase 3 (Hybrid Regex Engine & Audit Trail). See [archive/refactor-delegation-prompts.md](file:///Users/walsh.kang/Documents/GitHub/gradeline/docs/plans/archive/refactor-delegation-prompts.md) for historical details.
- **End-State Architecture Refactoring**: Completed Slice 1 (State Decoupling), Slice 2 (Orchestrator Refactor), and Slice 3 (Zero-Trust Boundaries). See [archive/architecture-endstate.md](file:///Users/walsh.kang/Documents/GitHub/gradeline/docs/plans/archive/architecture-endstate.md) for historical details.
- **Trust Loop & Visual Audit**: Completed Phase 1 to Phase 5. See [archive/trust-loop-and-visual-audit.md](file:///Users/walsh.kang/Documents/GitHub/gradeline/docs/plans/archive/trust-loop-and-visual-audit.md) for historical details.
- **Review Server UX Improvements (Phase 4)**: Completed automated E2E integration testing with Playwright browser testing and local mirror fallbacks. See [archive/review-server-ux-improvements.md](file:///Users/walsh.kang/Documents/GitHub/gradeline/docs/plans/archive/review-server-ux-improvements.md) for historical details.
- **Stability, Decomposition & Browser-First Grading (Waves 1, 2 & 3)**: 
  - Completed Wave 1 (Touch-First UX split-screen, Coordinate Mapping for scans/rotation, PDF Annotation Overlap mitigation, and Reviewed State indicators in Matrix View).
  - Completed Wave 2 (Golden-Output integration testing, stateless Orchestrator modularization into `grading.py`/`preprocessing.py`, D2L metadata ZIP import exclusion, and CLI interactive bypass).
  - Completed Wave 3 (Workflow CLI decomposition, GitHub Actions CI pipeline setup, and documentation housekeeping).
  - Completed Wave 4 Setup & Export (Browser File Upload & Profile Setup via `python-multipart`, Export Feedback & Browser Download via dynamic backend attachments).
  - Integrated sub-part grading calculations, YAML validator schemas, and judge LLM critique/automatic fixes recorded cleanly in `review_state.json`.
  - See [archive/stability-decomposition-browser-first.md](file:///Users/walsh.kang/Documents/GitHub/gradeline/docs/plans/archive/stability-decomposition-browser-first.md) for historical details.

## Current Objective
Executing the remainder of Wave 4 from the [Gradeline Unified Roadmap](file:///Users/walsh.kang/Documents/GitHub/gradeline/docs/plans/roadmap.md) (LLM Cost Breakdown Dashboard, Regex Pre-Check flags, and Judge LLM Audit).
