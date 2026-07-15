# Gradeline Architectural Guardrails

## Grade Integrity (MUST)
- Never assign a non-zero grade to a student with no submission match.
- Never promote REVIEW_REQUIRED to a passing grade automatically.
- All grades in brightspace_grades_import.csv must trace back to an LLM 
  verdict or regex pre-check recorded in grading_audit.csv.
- Judge LLM critiques and automated fixes must be injected into `review_state.json` rather than mutating `grading_audit.csv` directly, ensuring a single source of truth across the UI, audit DB, and Brightspace export.

## Feedback Integrity (MUST)
- Never annotate a point deduction on a student PDF without a short_reason.
- If the LLM feedback is dropped (e.g. third-person), fall back to the 
  rubric's short_note_fail — never leave it blank.
- Rubric YAML must have a non-empty short_note_fail for every question.

## Config Hierarchy (MUST)
- Resolution order: configs/defaults.toml → profile TOML → CLI flags.
- Never hardcode model names outside of configs/ or FREE_TIER_LIMITS.
- Profile TOMLs that omit `model` automatically inherit DEFAULT_MODEL.

## Zero-Trust State Management (MUST)
- Never crash the pipeline on individual submission errors (e.g. corrupted PDFs, LLM invalid schema, OCR failures).
- Catch all unhandled exceptions, flag the submission as `REVIEW_REQUIRED` with a score of 0, save a checkpoint, and gracefully proceed to the next student.

## Additional Scoring Rules
- `rounding_error` verdicts must be fully forgiven and scored identically to `correct` (1.0).
