# Gradeline Architecture: The Ideal End-State

This document captures the overarching mental model for Gradeline and outlines the roadmap to reach the polished "ideal end-state."

## The Mental Model: A Unidirectional Assembly Line
Gradeline is structured as a highly deterministic ETL (Extract, Transform, Load) pipeline for spatial grading. Data flows strictly in one direction across fully isolated stages:

1. **Ingestion & Profiling** (`workflow_cli.py`): Takes a Brightspace "Download All" zip, matches it to a specific configuration profile, and normalizes the files.
2. **Stage 1: Extract (The Spatial Map)** (`extract.py`): Runs Tesseract OCR (with vision fallback) to build a "Block Registry"—a literal map of where every word lives on the X/Y axis of the page.
3. **Stage 1.5: Regex Pre-check (Hybrid Pipeline)** (`precheck.py`): A fast, localized regex pass over the extracted text blocks for cost/speed optimization. Perfect matches bypass the LLM.
4. **Stage 2: Grade (The Reasoning Engine / LLM Factory)** (`llm_factory.py`): Routes the grading request (via Gemini, OpenAI, or Anthropic). Outputs structured JSON containing a grading verdict and the exact `block_id` used as evidence. It does not handle drawing or file saving.
5. **Stage 3: Annotate (The Printer)** (`annotate.py`): Takes the `block_id` from the model (or regex), looks it up in the Block Registry, and stamps a mark (✓/✗) on that exact coordinate.
6. **Stage 4: Review & Finalize (The Human Arbiter)** (`review/server.py`): The local web app allows instructors to quickly audit the pipeline's work, modify the state JSON, and trigger `report.py` to dump the final Brightspace-ready CSV.

---

## Roadmap to the End State

To achieve extreme accuracy (fail-closed), cost/speed optimization (deterministic pre-checks), and maintainability, we need to finalize the following architectural pillars:

### 1. The "Thin" CLI & The Orchestrator
**Current State:** `cli.py` is somewhat bloated, directly managing concurrency, rate limiters, checkpoints, and high-level workflow loops.
**End State:**
- `cli.py` is stripped down to nothing but an argument parser.
- It immediately instantiates a `GradingConfig` dataclass and hands it to a dedicated `orchestrator.py` (or `pipeline.py`).
- The Orchestrator completely encapsulates the thread pools, `RateLimiterRegistry`, and checkpoints.
- The CLI is strictly responsible for printing progress bars to humans or yielding JSON payloads to AI agents.

### 2. The Hybrid Grading Engine (Fast + Smart)
**Current State:** Mostly achieved! We recently added the regex pre-check engine.
**End State:**
- 100% deterministic evaluation where possible.
- The system runs the fast, localized regex pass over the extracted text blocks first.
- Perfect regex matches yield a full score immediately.
- Only if the deterministic check fails does it trigger the LLM to do "fuzzy" reasoning.

### 3. Zero-Trust State Management
**Current State:** We have checkpoints and try/except blocks, but "fail-closed" can be more rigorously enforced to guarantee zero crashes on malformed data.
**End State:**
- "Fail-closed" principle is baked in at every level.
- If a PDF is corrupted, a folder is missing, or the LLM hallucinates, the system **never** crashes or guesses.
- Instead, it catches the exception, flags the submission as `REVIEW_REQUIRED`, scores it a 0 or blank, saves a checkpoint (`checkpoint.py`), and gracefully proceeds to the next student.

### 4. The Human-in-the-Loop Flywheel
**Current State:** The Review App works and supports CSV export.
**End State:**
- The Review App acts as a rapid-fire triage queue rather than just a passive viewer.
- Keyboard shortcuts (e.g., `j/k`) for flying through flagged submissions.
- Fluid drag-and-drop annotation marks.
- A single "Export" action automatically regenerates the Brightspace CSV and the finalized PDFs, applying the human overrides back onto the artifacts.

---

## Brainstorming & Next Steps

*What do we need to implement to get there?*

1. **Phase 1: Refactor `cli.py` into an Orchestrator**
   - Extract the `ThreadPoolExecutor` and rate limiting logic from `cli.py` into a new `orchestrator.py`.
   - Create a clean `GradingConfig` dataclass to pass state cleanly.

2. **Phase 2: Bulletproof Zero-Trust Fail-Closed Handling**
   - Review the primary processing loop in the orchestrator.
   - Wrap the pipeline (`extract -> grade -> annotate`) in a robust try-except.
   - Explicitly define a `SubmissionResult.from_error()` factory method to deterministically generate a result that matches the schema expected by the CSV exporter and Review App.
   - Ensure the fallback state correctly emits `REVIEW_REQUIRED` and prevents downstream crashes.

~~3. **Phase 3: Review App Enhancements**~~ *(Already completed! `j/k` navigation and drag-and-drop are fully implemented in `grader/review/static/app.js`)*

---

## Execution Slices (Delegation Prompts)

To ensure we maintain a stable, fail-closed pipeline during the refactoring, the work is sliced into three distinct, verifiable prompts:

### Slice 1: State Decoupling (`GradingConfig`)
**Goal:** Disentangle the massive list of arguments currently passed around in `cli.py` and `score_submission` without altering the concurrency loop.
- **Tasks:**
  1. Define a strict `GradingConfig` dataclass in a new module (e.g., `grader/orchestrator.py` or `grader/config_types.py`).
  2. Update `parse_args` in `cli.py` to instantiate `GradingConfig` from the raw CLI arguments.
  3. Refactor `grade_one_submission` and the `process_student` / `annotate_and_finish` closures to accept the single `GradingConfig` object instead of 20+ separate arguments.
  4. Ensure no core logic or threading behavior changes.
- **Verification:** Run `pytest tests/test_workflow_cli.py` and `tests/test_cli_ui.py` to ensure all existing pipeline tests still pass.

### Slice 2: The Orchestrator Skeleton
**Goal:** Extract the `ThreadPoolExecutor`, `RateLimiterRegistry`, and high-level pipeline loop out of the bloated `cli.py`.
- **Tasks:**
  1. Create a primary `Orchestrator` class in `grader/orchestrator.py`.
  2. Move the `process_student`, `annotate_and_finish`, and thread-pool draining (`FIRST_COMPLETED`) logic from `cli.py` into `Orchestrator.run(config: GradingConfig, units: list[SubmissionUnit])`.
  3. Move the `RateLimiterRegistry` and Checkpoint handling into the Orchestrator.
  4. Strip `cli.py` so it simply parses arguments, sets up the `DiagnosticsCollector` / UI, and calls `Orchestrator().run()`.
- **Verification:** Verify that `concurrency`, interrupts (Ctrl+C), and checkpointing tests continue to pass with the new structural boundary.

### Slice 3: Zero-Trust Boundaries & `SubmissionResult.from_error()`
**Goal:** Bulletproof the Orchestrator against corrupted data, OCR crashes, and LLM hallucinations.
- **Tasks:**
  1. Expand `build_failed_submission_result` inside `cli.py` (now `orchestrator.py`) into a formal `SubmissionResult.from_error(error: Exception, ...)` factory method in `types.py`.
  2. Guarantee that this factory method deterministically generates a fallback state with `verdict="needs_review"` and a `0` grade for the CSV exporter.
  3. Wrap the core `extract -> precheck -> grade -> annotate` execution within the Orchestrator with a rigorous top-level `try/except`.
  4. Ensure any unhandled `Exception` triggers `SubmissionResult.from_error()`, logging the error and proceeding gracefully to the next student without crashing.
- **Verification:** Introduce targeted unit tests in `test_score.py` or `test_cli_errors.py` that intentionally raise exceptions during extraction or grading, asserting that the orchestrator falls back to a perfect `SubmissionResult` instead of a crash.
