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
| **6** | W6-CRITERIA | Structured Scoring Criteria Schema | M | Flash | Planned | Feedback #19 |
| **Backlog** | BL-DOCX | Word/TXT Solutions Keys Support | M | Flash | Backlog | Feedback #1 |
| **Backlog** | BL-SEARCH | Smart Candidate Search in Downloads | S | Flash | Backlog | Feedback #3 |

---

## Wave 6 — Extraction Quality & Rubric Precision

These tasks improve grading accuracy for math-heavy and complex-rubric assignments. No architectural prerequisites — both are opt-in features that leave default behavior unchanged.

---

### W6-CRITERIA: Structured Scoring Criteria Schema

**Origin**: Feedback #19
**Size**: Medium (~4–6 hours) · **Tier**: Flash

> [!IMPORTANT]
> The free-text `scoring_rules` field can lead to ambiguous LLM interpretation of partial credit. This task adds an optional structured `scoring_criteria` checklist that gives the LLM discrete, verifiable requirements — improving consistency for complex questions while remaining fully backward-compatible.

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Add an optional `scoring_criteria` list to the rubric question schema for discrete, structured evaluation criteria alongside the existing free-text `scoring_rules`.

Observed problem: The `scoring_rules` field is free-text, which can lead to ambiguous LLM interpretation of partial credit thresholds and methodology requirements. For example, "If the student sets up correct hypergeometric formulas but makes an arithmetic error, award partial credit (0.5)" — the LLM might award 0.5 for one formula right and one wrong, or for the right family but wrong parameters.

Files to modify:
- grader/types.py (new dataclass + field on QuestionRubric)
- grader/config.py (parse from YAML)
- grader/gemini_client.py (inject into grading prompt)
- grader/judge.py (include in judge context)
- grader/review/types.py (serialize for review UI)

## 1. Schema: add ScoringCriterion dataclass and field
In types.py, add a new frozen dataclass before QuestionRubric:

```python
@dataclass(frozen=True)
class ScoringCriterion:
    requirement: str
    weight: float = 1.0
    partial_if: str = ""
```

Add to QuestionRubric:
```python
    scoring_criteria: list[ScoringCriterion] = field(default_factory=list)
```

## 2. Config: parse scoring_criteria from YAML
In config.py load_rubric(), after parsing `requires_work`, add:

```python
scoring_criteria_raw = item.get("scoring_criteria", [])
scoring_criteria = []
for sc in scoring_criteria_raw:
    if not isinstance(sc, dict):
        raise ValueError(f"Each scoring_criteria entry in question '{q_id}' must be a mapping.")
    scoring_criteria.append(ScoringCriterion(
        requirement=str(sc.get("requirement", "")).strip(),
        weight=float(sc.get("weight", 1.0)),
        partial_if=str(sc.get("partial_if", "")).strip(),
    ))
```

Pass `scoring_criteria=scoring_criteria` to the QuestionRubric constructor.

Validation: if any criterion has an empty `requirement`, raise ValueError.

## 3. Prompt injection: format as structured checklist
In gemini_client.py, locate where `scoring_rules` is injected into the grading prompt (around line ~896 and ~1667). When `question.scoring_criteria` is non-empty, append a structured block AFTER the free-text scoring_rules:

```python
if question.scoring_criteria:
    criteria_lines = ["\nStructured Scoring Criteria (evaluate each independently):"]
    for i, sc in enumerate(question.scoring_criteria, 1):
        line = f"  {i}. [weight={sc.weight}] {sc.requirement}"
        if sc.partial_if:
            line += f" — Partial credit if: {sc.partial_if}"
        criteria_lines.append(line)
    criteria_lines.append(
        "\nScore this question as the weighted sum of met criteria. "
        "In your logic_analysis, explicitly state which criteria were met/unmet."
    )
    prompt_text += "\n".join(criteria_lines)
```

Do NOT remove or replace the existing `scoring_rules` text — the structured criteria supplements it.

## 4. Judge context: include criteria
In judge.py run_judge(), where question context is built (around line ~111), add structured criteria if present:

```python
if q_rubric.scoring_criteria:
    for i, sc in enumerate(q_rubric.scoring_criteria, 1):
        prompt_parts.append(f"  Criterion {i} [w={sc.weight}]: {sc.requirement}")
        if sc.partial_if:
            prompt_parts.append(f"    Partial if: {sc.partial_if}")
```

## 5. Review types: serialize for UI
In grader/review/types.py, when building the question rubric dict for the review API, include:
```python
"scoring_criteria": [
    {"requirement": sc.requirement, "weight": sc.weight, "partial_if": sc.partial_if}
    for sc in q_rubric.scoring_criteria
]
```

## 6. Scoring computation (CRITICAL)
When scoring_criteria is present and the LLM returns verdict="partial":
- If all criteria have explicit weights, the partial_credit score should be computed as the weighted sum of met criteria divided by total weight, INSTEAD of using the flat `partial_credit` value from RubricConfig.
- This requires the LLM to report which criteria it considered met. Add a note in the prompt: "List met criteria indices in your logic_analysis, e.g. 'Criteria 1,3 met; Criterion 2 unmet.'"
- For now, keep the flat partial_credit as a fallback if criteria are present but the LLM doesn't clearly indicate which were met.
- Do NOT change scoring for questions without scoring_criteria — behavior must be identical to today.

## 7. Backward compatibility
- Rubrics without `scoring_criteria` must behave identically to today — the field defaults to an empty list.
- The AI rubric generator (generate_rubric_from_solutions) does NOT need to emit scoring_criteria yet — that is a separate follow-up task.
- The existing `scoring_rules` free-text field stays as the primary instruction; `scoring_criteria` is supplementary.

## Verification
- Write tests in tests/test_config.py:
  - test_load_rubric_with_scoring_criteria: YAML with scoring_criteria parses correctly.
  - test_load_rubric_without_scoring_criteria: YAML without the field loads with empty list (no regression).
  - test_load_rubric_scoring_criteria_empty_requirement: raises ValueError.
- Write tests in tests/test_gemini_prompt.py:
  - Construct a QuestionRubric with scoring_criteria and verify the prompt string contains "Structured Scoring Criteria" and the individual requirements.
  - Construct one without and verify the prompt does NOT contain that section.
- Run: PYTHONPATH=. .venv/bin/pytest tests/test_config.py tests/test_gemini_prompt.py -x -v
```
</details>

---

## Backlog

| Task ID | Title | Size | Notes |
|:---:|:---|:---:|:---|
| BL-DOCX | Word/TXT/MD Solutions Keys Support | M | Lower friction for instructors. (Note: Student submission DOCX conversion already exists in `discovery.py`; this task is specifically for converting/parsing solution keys). |
| BL-SEARCH | Smart Candidate Search in Downloads | S | Sort by modified date, weight profile name matches higher. |
| BL-VISION-AUTO | Auto-Detect Math-Heavy Pages | M | Heuristic to detect Tesseract gibberish on math content and selectively re-extract via Gemini. Follow-up to W6-VISION — the flag becomes a hard override, the heuristic becomes the smart default. |
