# Gradeline Architecture: The Ideal End-State

This document captures the overarching mental model for Gradeline and outlines the roadmap to reach the polished "ideal end-state."

## The Mental Model: A Unidirectional Assembly Line
Gradeline is structured as a highly deterministic ETL (Extract, Transform, Load) pipeline for spatial grading. Data flows strictly in one direction across fully isolated stages:

1. **Ingestion & Profiling** (`workflow_cli.py`): Takes a Brightspace "Download All" zip, matches it to a specific configuration profile, and normalizes the files.
2. **Stage 1: Extract (The Spatial Map)** (`extract.py`): Runs Tesseract OCR (with vision fallback) to build a "Block Registry"—a literal map of where every word lives on the X/Y axis of the page.
3. **Stage 2: Grade (The Brain)** (`gemini_client.py`): The reasoning model looks at the rubric and the PDF. It outputs structured JSON containing a grading verdict and the exact `block_id` used as evidence. It does not handle drawing or file saving.
4. **Stage 3: Annotate (The Printer)** (`annotate.py`): Takes the LLM's `block_id`, looks it up in the Block Registry, and stamps a mark (✓/✗) on that exact coordinate.
5. **Stage 4: Review & Finalize (The Human Arbiter)** (`review/server.py`): The local web app allows instructors to quickly audit the pipeline's work, modify the state JSON, and trigger `report.py` to dump the final Brightspace-ready CSV.

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
   - Ensure the fallback state correctly emits `REVIEW_REQUIRED` and writes the audit row.

3. **Phase 3: Review App Enhancements**
   - Audit the frontend JS for `j/k` keyboard navigation.
   - Ensure drag-and-drop bounding box logic perfectly syncs back to the backend state.

*(Feel free to edit this file or add comments as we iterate on the plan!)*
