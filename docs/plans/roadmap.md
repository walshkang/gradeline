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
| **7** | W7-NUMERIC | Numeric Answer DSL (`expected_numeric`) | M | Flash | Planned | Feedback #22 |
| **Backlog** | BL-DOCX | Word/TXT Solutions Keys Support | M | Flash | Backlog | Feedback #1 |
| **Backlog** | BL-SEARCH | Smart Candidate Search in Downloads | S | Flash | Backlog | Feedback #3 |

---

## Wave 6 — Extraction Quality & Rubric Precision

These tasks improve grading accuracy for math-heavy and complex-rubric assignments. No architectural prerequisites — both are opt-in features that leave default behavior unchanged. (Both W6-VISION and W6-CRITERIA have been shipped; prompt details are archived in [shipped-waves-archive.md](archive/shipped-waves-archive.md)).

---

## Wave 7 — Auto-Rubric Generation & Precision

These tasks enhance the AI rubric generation pipeline and simplify rubric authoring based on empirical grading reflection. (W7-PROMPT prompt details are archived in [shipped-waves-archive.md](archive/shipped-waves-archive.md)).

---

### W7-NUMERIC: Numeric Answer DSL (`expected_numeric`)

**Origin**: Reflection #2 (HW3 Rubric Evaluation / Feedback #22)
**Size**: Medium (~4–5 hours) · **Tier**: Flash

```
Implement a high-level `expected_numeric` syntax in rubric YAML to automatically compile numeric value ranges into hardened regexes.

Files to modify:
- grader/types.py (QuestionRubric schema)
- grader/config.py (Rubric loader & validator)
- grader/workflow/profile_utils.py (YAML generator templates)
- tests/test_rubric_normalization.py

## Key Requirements

1. YAML Schema Extension:
   Allow questions in rubric YAML to specify an `expected_numeric` dictionary:
   expected_numeric:
     value: 0.0808
     tolerance: 0.001
     allow_percent: true  # optional, default true

2. Automatic Regex Compilation:
   In `load_rubric()` in `grader/config.py`:
   - If `expected_numeric` is present, derive the bounds `[min_val, max_val] = [value - tolerance, value + tolerance]`.
   - Programmatically compile regex patterns enforcing word boundaries `\b` and supporting:
     * Standard decimal forms (e.g., `0.0808`, `.0808`, `0.081`, `0.080`).
     * Optional leading zeros and trailing precision options.
     * Percentage forms if `allow_percent` is True (e.g., `8.08%`, `8.1%`).
   - Append compiled regexes into `question.expected_answers` so existing `regex_precheck` logic consumes them seamlessly with zero changes to precheck execution.

3. Backward Compatibility:
   - Retain full support for raw `expected_answers` string lists. Both `expected_numeric` and `expected_answers` can coexist or be used independently.

4. Validation & Guardrails:
   - Pass compiled regexes through `validate_expected_answers()` to ensure compiled numeric patterns don't collide with question labels or miss word boundaries.

## Verification
- Add unit tests in `tests/test_rubric_normalization.py` testing `expected_numeric` compilation for decimals, percentages, and tolerances.
- Run `PYTHONPATH=. .venv/bin/pytest tests/test_rubric_normalization.py tests/test_precheck.py`.
```

---

---

## Backlog

| Task ID | Title | Size | Notes |
|:---:|:---|:---:|:---|
| BL-DOCX | Word/TXT/MD Solutions Keys Support | M | Lower friction for instructors. (Note: Student submission DOCX conversion already exists in `discovery.py`; this task is specifically for converting/parsing solution keys). |
| BL-SEARCH | Smart Candidate Search in Downloads | S | Sort by modified date, weight profile name matches higher. |
| BL-VISION-AUTO | Auto-Detect Math-Heavy Pages | M | Heuristic to detect Tesseract gibberish on math content and selectively re-extract via Gemini. Follow-up to W6-VISION — the flag becomes a hard override, the heuristic becomes the smart default. |

