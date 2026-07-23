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
- **Codebase Modularization & Refactoring (Wave 9 Progress)**:
  - Completed `W9-ANNOT-STATE` (Extract AnnotationSession Dataclass `[Track A1]`). Encapsulated `placed_rects`, `rendered`, `rendered_subparts`, `placement_details` inside `AnnotationSession` in `grader/annotate.py` with clean state management methods (`clear_placed_rects`, `mark_rendered`, `mark_subpart_rendered`, `record_placement`, `update_results`).
  - Completed `W9-GEMINI-SCHEMAS` (Extract Gemini Schemas & Prompts `[Track B1]`). Decomposed `grader/gemini_client.py` by extracting Pydantic response models, constants, and prompt builder functions into `grader/gemini_schemas.py` with zero API dependencies while maintaining re-exported backward compatibility.
  - Completed `W9-ANNOT-RENDERER` (Extract PDF Renderer Module `[Track A2]`). Decomposed PyMuPDF drawing and annotation operations from `grader/annotate.py` into `grader/pdf_renderer.py` (`insert_mark`, `add_movable_freetext_annotation`, `find_non_overlapping_rect`, `is_dark_background`, `add_band_header`, `add_fallback_summary`, `offset_mark_point`) with re-exported backward compatibility.
  - Completed `W9-ORCH-STAGES` (Extract Orchestrator Stages `[Track C]`). Decomposed `grader/orchestrator.py` by extracting pipeline phase handlers into `grader/stages/` (`preprocessing_stage`, `grading_stage`, `annotation_stage`, `report_stage`, `regrade_stage`), leaving `Orchestrator` as a thin coordinator with full backward compatibility.
  - Completed `W9-CLI-COMMANDS` (Extract Workflow CLI Subcommands `[Track D]`). Decomposed `grader/workflow_cli.py` (from 1,206 to 421 lines) by extracting CLI helpers into `grader/workflow/cli_utils.py` and subcommand handlers into `grader/workflow/commands/` (`run`, `regrade`, `spot_grade`, `clear_run`, `grade_new`), maintaining 100% backward compatibility via re-exported top-level symbols.
  - Completed `W9-ANNOT-RESOLVER` (Extract Location Resolver Module `[Track A3]`). Decomposed `grader/annotate.py` by extracting pure placement strategy functions, anchor text searching, OCR block heuristics, coordinate mapping, and subpart label normalization into `grader/location_resolver.py`, maintaining re-exported backward compatibility.
  - Completed `W9-GEMINI-NORMALIZE` (Extract Response Normalization `[Track B2]`). Decomposed `grader/gemini_client.py` by extracting response parsing, sub-part aggregation, feedback derivation, locator normalization, and draft rubric normalization logic into `grader/gemini_normalize.py`, maintaining 100% re-exported backward compatibility.
  - Completed `W9-GEMINI-RESILIENCE` (Extract Resilience & Thin Client `[Track B3 - Final]`). Decomposed `grader/gemini_client.py` by extracting rate limiting, caching, exponential backoff retries, file readiness polling, cache key calculations, and error mapping logic into `grader/gemini_resilience.py` (`GeminiCacheStore`, `call_with_backoff`, `wait_for_file_active`, etc.), refactoring `GeminiGrader` into a thin transport API client with full re-exported backward compatibility.
  - Completed `W9-ANNOT-PIPELINE` (Refactor Annotator Pipeline `[Track A4 - Final]`). Decomposed `annotate_submission_pdfs` in `grader/annotate.py` into modular single-responsibility pipeline helpers (`_annotate_single_pdf`, `_process_question_annotation`, `_process_subparts_annotation`, `_append_unresolved_summary`), extracted `AnnotationSession` into `grader/annotation_state.py`, and extracted PyMuPDF rendering logic into `grader/pdf_renderer.py`, preserving 100% re-exported backward compatibility.
- **Detailed prompt specifications for shipped waves are archived in [archive/shipped-waves-archive.md](docs/plans/archive/shipped-waves-archive.md).**

## Current Objective
Wave 9 Modularization & Refactoring is 100% complete! Proceeding to Backlog & Web Workstation initiatives in [Gradeline Unified Roadmap](docs/plans/roadmap.md):
- **BL-SEC**: App Hardening & Security Auditing (`bandit`, `pip-audit`, untrusted prompt isolation)
- **BL-DOCX**: Word/TXT/MD Solution Keys Support
- **BL-VISION-AUTO**: Auto-Detect Math-Heavy Pages
- **BL-WEB-WORKSTATION**: Unified Web-Based Grading Workstation

## Next Strategic Direction (Professor Web Workstation & UX)
- **Intuitive Web App for Non-Tech Professors**: Building out the Review Server into a self-describing workstation with opt-in instructions and unobtrusive autosave visual feedback (`BL-SAVED-ANIM`).
- **Unified Web Workstation Vision (`BL-WEB-WORKSTATION`)**: Expanding the web interface to eventually cover assignment ingestion and auto-rubric creation, giving non-tech professors a single browser workstation for the entire assignment grading lifecycle.
