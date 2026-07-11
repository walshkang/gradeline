# Gradeline Architectural Guardrails

## Grade Integrity (MUST)
- Never assign a non-zero grade to a student with no submission match.
- Never promote REVIEW_REQUIRED to a passing grade automatically.
- All grades in brightspace_grades_import.csv must trace back to an LLM 
  verdict or regex pre-check recorded in grading_audit.csv.

## Feedback Integrity (MUST)
- Never annotate a point deduction on a student PDF without a short_reason.
- If the LLM feedback is dropped (e.g. third-person), fall back to the 
  rubric's short_note_fail — never leave it blank.
- Rubric YAML must have a non-empty short_note_fail for every question.

## Config Hierarchy (MUST)
- Resolution order: configs/defaults.toml → profile TOML → CLI flags.
- Never hardcode model names outside of configs/ or FREE_TIER_LIMITS.
- Profile TOMLs that omit `model` automatically inherit DEFAULT_MODEL.
