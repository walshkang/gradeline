# Gradeline Unified Roadmap

This document is the single source of truth for all planned improvements. It merges the [stability & decomposition plan](stability-decomposition-browser-first.md) with the [feedback & improvements log](../feedback.md), de-duplicates overlapping items, and organizes everything into execution waves with copy-pasteable agent prompts.

> [!NOTE]
> Items marked ✅ have been verified as shipped in the current codebase via git history and code audit. Items marked 🔀 have been merged into another task to avoid duplicate work.

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
| **5** | W5-ANNOT | PDF Annotation Editing (Option C) | L | Pro | Todo | Plan Phase 9 |
| **Backlog** | BL-DOCX | Word/TXT Solutions Keys Support | M | Flash | Backlog | Feedback #1 |
| **Backlog** | BL-SEARCH | Smart Candidate Search in Downloads | S | Flash | Backlog | Feedback #3 |
| **Backlog** | BL-VISION | Force Vision Extraction for Math | M | Flash | Backlog | Feedback #18 |
| **Backlog** | BL-CRITERIA | Structured Scoring Criteria Schema | M | Pro | Backlog | Feedback #19 |

---

## Wave 1 — Grading Quality & Review UX (Do Now)

These tasks directly improve the quality of a live grading run and the reviewer's experience. No architectural prerequisites.

---

### W1-UX: Touch-First UX + Viewer Scroll Focus

**Merges**: Plan Phase 0 + Feedback #11
**Size**: Medium (~4–6 hours) · **Tier**: Flash

> [!IMPORTANT]
> Feedback item #11 (auto-scroll to focus) is a subset of Phase 0's "Smooth Scroll to PDF Coordinates" specification. They are merged here to avoid doing the scroll work twice.

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Implement the Touch-First UX improvements for the Gradeline review server.

Files to modify:
- grader/review/static/styles.css
- grader/review/static/index.html
- grader/review/static/app.js

## 1. Split-Screen Mobile Layout
In styles.css, modify the responsive media query (@media (max-width: 1180px)) to use a split-screen layout:
- Set .viewer to a fixed height (55vh) with overflow: auto.
- Set .editor to occupy remaining height as a scrollable bottom-sheet panel.
- Both panels must be simultaneously visible — no full-height stacking.

## 2. One-Tap Verdict Buttons & Auto-Advance
In index.html, add a row of large, colorful buttons for verdicts (Correct, Rounding Error, Partial, Incorrect, Needs Review) alongside or replacing #verdictSelect.
Add an Auto-Advance toggle checkbox: <input type="checkbox" id="autoAdvanceToggle" checked />.
In app.js:
- When a verdict button is tapped, save the verdict, set reviewed_final to true.
- If Auto-Advance is enabled, find the next unreviewed question in #questionNavGrid and call selectQuestion(nextQId).

## 3. Smooth Scroll to PDF Coordinates
In app.js, within selectQuestion (after loadCurrentPage resolves and renderMarker runs):
- Calculate pixel offset of the marker on the page image.
- Scroll ui.imageWrap smoothly to center the marker:
  ui.imageWrap.scrollTo({
    top: py - ui.imageWrap.clientHeight / 2,
    left: px - ui.imageWrap.clientWidth / 2,
    behavior: "smooth"
  });
- Add a brief CSS keyframe scale/opacity pulse to #marker on question selection.
- Add ::after padding on .marker for larger touch targets (minimum 32x32px).

## Verification
- Open the review server at localhost, select a submission, click through questions — the viewer should auto-scroll to center the marker each time.
- On a narrow viewport (<1180px), both the PDF viewer and editor panel should be visible simultaneously.
```
</details>

---

### W1-COORD: Coordinate Mapping for Scanned & Rotated PDFs

**Origin**: Feedback #10
**Size**: Medium (~4–6 hours) · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Fix coordinate mapping for scanned and rotated PDF submissions in the annotation pipeline.

Observed problem: Handwritten submissions (e.g. Aldo Arossa's) get annotations placed at wrong locations because the code does not account for page rotation or CropBox/MediaBox differences.

Files to modify:
- grader/annotate.py (resolve_model_location, point_to_normalized, text_annotation_rect_from_baseline, offset_mark_point)

## 1. Respect page.rotation
In resolve_model_location(), after obtaining the page object, read page.rotation.
If rotation is non-zero (90, 180, 270), apply a coordinate transformation to the normalized 0-1000 coords before converting to page points:
- 90°:  new_x = y_norm, new_y = 1000 - x_norm
- 180°: new_x = 1000 - x_norm, new_y = 1000 - y_norm
- 270°: new_x = 1000 - y_norm, new_y = x_norm

## 2. Use page.rect (which accounts for CropBox) consistently
Verify that all coordinate conversion uses page.rect (which PyMuPDF adjusts for CropBox/rotation) rather than raw MediaBox dimensions. page.rect already accounts for rotation in PyMuPDF, so the derotation may need to check page.rotation_matrix instead. Test both paths.

## 3. Add fallback margin anchors for text-less scanned pages
In find_anchor_in_doc(), if page.search_for() returns no matches for any token (common in pure-scan PDFs), add a fallback that places the annotation in the right margin at an estimated vertical position based on the question's ordinal index within the rubric (e.g. y = page.rect.height * (question_index / total_questions)).

## Verification
- Run the annotation pipeline on Aldo Arossa's submission (a handwritten scanned PDF) and verify marks appear near the actual answers.
- Run on a standard typed PDF to verify no regression.
- Write a unit test in tests/test_annotate_rotation.py that creates a rotated single-page PDF with fitz, runs resolve_model_location with known coords, and asserts the output point falls within the visible page area.
```
</details>

---

### W1-OVERLAP: PDF Annotation Overlap Mitigation

**Origin**: Feedback #9
**Size**: Medium (~4–6 hours) · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Implement collision detection for PDF annotations to prevent overlapping marks.

Observed problem: When multiple sub-parts or adjacent questions map to nearby coordinates, their FreeText annotations overlap and become unreadable.

Files to modify:
- grader/annotate.py

## 1. Track placed annotation rects per page
Add a dictionary `placed_rects: dict[int, list[fitz.Rect]]` (keyed by page index) at the top of annotate_submission_pdfs(), before the loop over rubric questions.

## 2. Create a nudge helper
Create a function `find_non_overlapping_rect(page, candidate_rect, placed_rects_for_page, max_nudge_px=200) -> fitz.Rect`:
- Check if candidate_rect intersects any rect in placed_rects_for_page using fitz.Rect.intersects().
- If it does, nudge candidate_rect downward by (candidate_rect.height + 4) pixels and re-check.
- Repeat up to max_nudge_px total offset. If still colliding, try nudging rightward instead.
- Return the final non-overlapping rect.

## 3. Integrate into insert_mark
In insert_mark(), after computing the annotation rect via text_annotation_rect_from_baseline():
- Call find_non_overlapping_rect() to get a collision-free rect.
- Use the adjusted rect for the annotation placement.
- Append the final rect to placed_rects[page.number].
- Update mark_point to match the adjusted rect's origin so the annotation subject metadata stays accurate.

Pass placed_rects into insert_mark from annotate_submission_pdfs (add it as a parameter).

## Verification
- Run annotation on a submission with many sub-parts on a single page (e.g. Question 7 with sub-parts a, b) and verify no overlapping annotations.
- Run on a submission with few questions and verify placement looks normal (no unnecessary shifting).
- Add a unit test that places 5 annotations at the same point and asserts all resulting rects are non-overlapping.
```
</details>

---

### W1-MATRIX: Reviewed State in Matrix View

**Origin**: Feedback #12
**Size**: Medium (~4 hours) · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Add reviewed-state visibility and toggle controls to the Matrix View.

Observed problem: The Matrix View does not show whether individual questions have been marked as "Reviewed", and there is no way to toggle review status from the matrix panel.

Files to modify:
- grader/review/api.py (get_matrix method)
- grader/review/static/app.js (renderMatrix, showMatrixDetail)
- grader/review/static/styles.css

## 1. Backend: include reviewed field in matrix cells
In api.py's get_matrix(), add "reviewed" to the cells dict:
  cells[q_id] = {
      "verdict": ...,
      "confidence": ...,
      "grading_source": ...,
      "evidence_quote": ...,
      "logic_analysis": ...,
      "reviewed": bool(final_payload.get("reviewed", False)),
  }

## 2. Frontend: show reviewed indicator on matrix cells
In app.js's renderMatrix(), after creating each cell div:
- If cellData.reviewed is true, add a CSS class "matrix-cell-reviewed" to the cell.
- Append a small checkmark span inside the cell: <span class="matrix-reviewed-badge">✓</span>

In styles.css, add:
  .matrix-cell-reviewed { box-shadow: inset 0 0 0 2px var(--green-500); }
  .matrix-reviewed-badge { position: absolute; top: 1px; right: 2px; font-size: 0.55rem; color: var(--green-600); }
  .matrix-cell { position: relative; }

## 3. Frontend: toggle reviewed from matrix detail panel
In showMatrixDetail(), add a "Mark Reviewed" checkbox after the existing content:
  <label><input type="checkbox" id="mdetailReviewedToggle" ${cellData.reviewed ? "checked" : ""} /> Reviewed</label>

Add an event listener on #mdetailReviewedToggle that:
- Calls apiPatch(`/api/submissions/${student.submission_id}/questions/${qId}`, { reviewed_final: checkbox.checked })
- Updates cellData.reviewed in the local matrixData
- Calls renderMatrix() to refresh the grid

## Verification
- Open the matrix view, verify reviewed questions show a green border + checkmark badge.
- Click a cell, toggle the "Reviewed" checkbox in the detail panel, verify the matrix grid updates immediately.
- Switch to the Review tab, verify the same question shows matching reviewed state.
```
</details>

---

## Wave 2 — Test Foundation & Core Decomposition

### W2-GOLDEN: Golden-Output Integration Test

**Origin**: Plan Phase 2
**Size**: Medium · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Create a golden-output integration test that runs extraction → pre-check → scoring end-to-end with a local fixture PDF.

See the full specification in docs/plans/stability-decomposition-browser-first.md, Phase 2.

Key deliverables:
1. Create tests/fixtures/ with sample_submission.pdf (3 simple questions), sample_rubric.yaml, and sample_solutions.pdf.
2. Create tests/test_integration_golden.py with:
   - test_regex_precheck_golden_output: all 3 questions return verdict="correct" via regex.
   - test_scoring_golden_output: final band is CHECK_PLUS.
   - test_annotation_golden_output: annotated PDF is valid.
3. Guard tests requiring pdftoppm/tesseract with shutil.which() skip conditions.

Verify: PYTHONPATH=. .venv/bin/pytest tests/test_integration_golden.py -x -v
```
</details>

---

### W2-ORCH: Orchestrator Decomposition

**Origin**: Plan Phase 3
**Size**: Large · **Tier**: Pro

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Decompose orchestrator.py into modular sub-packages. This is a pure refactor — no behavioral changes.

See the full specification in docs/plans/stability-decomposition-browser-first.md, Phase 3.

Key deliverables:
1. Extract grader/grading.py (~350 lines): grade_one_submission, collect_locator_candidates, apply_locator_candidates, progress callbacks.
2. Extract grader/preprocessing.py (~200 lines): compute_submission_pdf_hash, get_or_compute_preprocessing, compute_cache_key_for_submission, StageTiming, SubmissionTelemetry.
3. orchestrator.py shrinks to ≤900 lines. Re-export moved symbols for backward compatibility.

CRITICAL: orchestrator.py must call grade_one_submission() by bare name (not grading.grade_one_submission()) so that @patch("grader.orchestrator.grade_one_submission") in tests continues to work.

Verify: PYTHONPATH=. .venv/bin/pytest tests/ -x -q && PYTHONPATH=. .venv/bin/pytest tests/test_orchestrator_errors.py tests/test_orchestrator_cache.py tests/test_orchestrator_zero_trust.py -v
```
</details>

---

### W2-ZIP: Exclude Metadata in ZIP Import

**Origin**: Feedback #4
**Size**: Small (~1 hour) · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Update the Brightspace ZIP extraction to exclude D2L metadata files.

File to modify: grader/workflow_cli.py, function _extract_brightspace_zip (line ~1106).

After archive.extractall(temp_root), walk the extracted directory and delete files matching common D2L metadata patterns:
- index.html, index.htm, index.txt
- Any file whose name starts with "." (hidden files)

Also update discover_submission_units in grader/discovery.py to skip non-PDF files at the folder level (it already does via the .rglob("*.pdf") filter, but verify index.html doesn't end up in submission folders).

Verify: Extract a real Brightspace ZIP and confirm index.html is not present in the resulting submissions directory.
```
</details>

---

### W2-TTY: TTY Bypass for CLI Wizards

**Origin**: Feedback #2
**Size**: Small (~1 hour) · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Add a --non-interactive flag to the quickstart and setup CLI commands to bypass TTY checks.

Files to modify:
- grader/workflow_cli.py (argparse definitions and interactive prompt guards)

1. Add --non-interactive / --yes flag to the argument parser for quickstart/setup subcommands.
2. When the flag is set, skip all prompt_yes_no() and input() calls — use default values instead.
3. Ensure sys.stdin.isatty() guards allow non-interactive mode to proceed without error.

Verify: Run ./gradeline quickstart --profile test_auto --non-interactive and confirm it creates a default profile without prompting.
```
</details>

---

## Wave 3 — CLI Decomposition & CI

### W3-CLI: Workflow CLI Decomposition

**Origin**: Plan Phase 4
**Size**: Large · **Tier**: Pro

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Decompose workflow_cli.py into a grader/workflow/ package. Pure refactor — no behavioral changes.

See the full specification in docs/plans/stability-decomposition-browser-first.md, Phase 4.

Key deliverables:
1. Create grader/workflow/__init__.py re-exporting main and build_parser.
2. Extract grader/workflow/quickstart.py (~500 lines).
3. Extract grader/workflow/import_cmd.py (~200 lines).
4. Extract grader/workflow/profile_utils.py (~200 lines).
5. workflow_cli.py shrinks to ≤1200 lines.

Verify: PYTHONPATH=. .venv/bin/pytest tests/ -x -q && ./gradeline --help
```
</details>

---

### W3-CI: GitHub Actions CI

**Origin**: Plan Phase 5
**Size**: Medium · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Create a GitHub Actions CI pipeline.

See the full YAML specification in docs/plans/stability-decomposition-browser-first.md, Phase 5.

Key deliverables:
1. Create .github/workflows/test.yml with unit test job (Python 3.12/3.13/3.14 matrix) and E2E job (Playwright).
2. Add CI status badge to README.md.

Verify: Push to a branch and confirm the workflow runs green.
```
</details>

---

### W3-HOUSE: Housekeeping

**Origin**: Plan Phase 6
**Size**: Small · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Update context.md to reflect all completed work (decomposition, sub-part grading, judge critique, etc.).
Move completed plan documents to docs/plans/archive/.
Ensure docs/plans/roadmap.md is the canonical active plan.
```
</details>

---

## Wave 4 — Browser-First Setup & Analytics

### W4-UPLOAD: Browser File Upload & Profile Setup

**Origin**: Plan Phase 7
**Size**: Large · **Tier**: Pro

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Implement browser-based file upload and profile setup.

See the full specification in docs/plans/stability-decomposition-browser-first.md, Phase 7. Pay special attention to the Security Hardening section (path traversal, zip-slip, upload size limits).

Key deliverables:
1. Setup Dashboard UI in index.html with drag-zone uploads for Submissions ZIP, Solutions PDF, Rubric YAML, Brightspace CSV.
2. Multipart upload endpoints in server.py with streaming writes and size limits.
3. Non-interactive AI rubric generator extracted from maybe_generate_rubric_with_ai().
```
</details>

---

### W4-EXPORT: Export Feedback & Browser Download

**Merges**: Plan Phase 10 + Feedback #13
**Size**: Medium · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Replace the static Export button with a dropdown providing direct browser downloads and descriptive feedback.

Files to modify:
- grader/review/server.py (new GET routes)
- grader/review/static/index.html (dropdown menu)
- grader/review/static/app.js (download handlers)

1. Add download routes:
   - GET /api/export/csv → brightspace_grades_import_reviewed.csv
   - GET /api/export/audit → grading_audit_reviewed.csv
   - GET /api/export/pdfs → ZIP of reviewed PDFs
   - GET /api/export/bundle → complete ZIP with all artifacts
2. Replace the Export button with a dropdown menu offering each download option.
3. After export completes, show a toast listing the exact files and paths that were written, addressing Feedback #13.
```
</details>

---

### W4-COST: LLM Cost Breakdown Dashboard

**Origin**: Feedback #14
**Size**: Medium · **Tier**: Flash

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Track and display LLM API costs per run, per student, and per question.

Files to modify:
- grader/gemini_client.py (capture usage_metadata from API responses)
- grader/types.py (add token_usage fields to QuestionResult)
- grader/report.py (add cost columns to audit CSV)
- grader/review/api.py (include cost data in run outcomes summary)
- grader/review/static/app.js (render cost breakdown in Run Summary panel)

1. After each Gemini API call, parse usage_metadata from the response (input_tokens, output_tokens, cached_tokens).
2. Store token counts in QuestionResult and propagate through checkpoint serialization.
3. Create a cost calculator helper mapping model name → per-token pricing.
4. Display per-run and per-question cost summaries in the CLI output and in the review server's Run Summary section.
```
</details>

---

### W4-WORK: Regex Pre-Check `requires_work` Flag

**Origin**: Feedback #17
**Size**: Small (~1–2 hours) · **Tier**: Flash

> [!IMPORTANT]
> This closes a grading integrity gap where the regex pre-check auto-passes students who write only a final answer without showing required methodology. Per AGENTS.md: "Never assign a non-zero grade to a student with no submission match" — this extends that principle to methodology verification.

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Add a `requires_work` flag to the rubric schema so that regex pre-check matches on work-required questions still route to the Stage 2 LLM for methodology verification.

Files to modify:
- grader/types.py (QuestionRubric dataclass)
- grader/precheck.py (regex_precheck function)
- grader/grading.py (pass regex hint to LLM when requires_work skips precheck)

## 1. Schema: add requires_work field
In types.py, add `requires_work: bool = False` to the QuestionRubric dataclass.
In config.py load_rubric(), parse `requires_work` from the YAML (default False).

## 2. Pre-check: skip emission when requires_work is True
In precheck.py regex_precheck(), when all patterns match but `question.requires_work` is True:
- Do NOT add the question to the results dict (let it fall through to LLM grading).
- Instead, return the matched evidence in a separate dict (e.g., `hints`) so the caller can pass it to the LLM as context.

Update the function signature to return a tuple: `(results, hints)` where hints maps question_id → evidence_quote.

## 3. Update callers
In grading.py, update the call to regex_precheck to unpack both results and hints.
When building the LLM grading prompt for a question that has a hint, prepend a note:
"Note: The student's final answer appears to match the expected value ({evidence}). Focus your evaluation on whether the student showed the required methodology/setup."

## 4. Update rubric YAML
In configs/hw2.yaml, add `requires_work: true` to Problem 5 (expected value compensation).

## Verification
- Write a test in tests/test_precheck.py: a question with requires_work=True and matching expected_answers should NOT appear in prechecked results.
- Write a test: a question with requires_work=False (default) and matching answers SHOULD still appear in prechecked results (no regression).
- Run: PYTHONPATH=. .venv/bin/pytest tests/test_precheck.py -x -v
```
</details>

---

### W4-JUDGE: Judge LLM Rounding Error & Partial Credit Audit

**Origin**: Feedback #20
**Size**: Small (~1–2 hours) · **Tier**: Flash

> [!IMPORTANT]
> Per AGENTS.md, `rounding_error` verdicts are fully forgiven (scored 1.0). Without explicit judge scrutiny, the primary grader can over-assign this verdict as a safe default. This task adds guardrails to catch hallucinated rounding error and unsupported partial credit.

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Augment the Judge LLM prompt to explicitly scrutinize rounding_error and partial_credit verdicts.

File to modify:
- grader/judge.py (run_judge function, prompt construction)

## 1. Expand the judge prompt
At line 121 (the final instruction appended to prompt_parts), replace the existing instruction with an expanded version that includes:

a) General instruction (existing): "Identify any grading mistakes. If the verdict is incorrect or partial, ensure a proposed_reason is provided. If you do not have a reason, fall back to the short_note_fail."

b) Rounding error audit (new): "CRITICAL: For any question with verdict 'rounding_error', verify that the evidence_quote demonstrates a fundamentally correct method with only a minor arithmetic or rounding slip. If the evidence shows a wrong formula, missing setup, or conceptual error, propose verdict 'incorrect' or 'needs_review' with needs_fix=true. A rounding_error verdict is fully forgiven (scored 1.0), so false positives here directly inflate grades."

c) Partial credit audit (new): "For any question with verdict 'partial', verify that the evidence_quote is non-empty and actually supports the logic_analysis. If the evidence_quote is empty, missing, or contradicts the claimed partial credit reasoning, set needs_fix=true and propose verdict 'needs_review'."

d) Empty evidence audit (new): "For any non-correct verdict, if evidence_quote is blank or generic (e.g., 'N/A', 'not found'), flag it as needs_fix=true."

## 2. No schema changes needed
The existing JudgeQuestionCritique schema already supports proposed_verdict and needs_fix — the prompt changes alone are sufficient.

## Verification
- Run the judge on a completed grading run: ./gradeline judge --profile hw2
- Inspect the updated review_state.json and verify that judge_critique entries for rounding_error verdicts include specific critique text about methodology verification.
- Write a unit test in tests/test_judge_prompt.py that constructs a mock audit row with verdict='rounding_error' and empty evidence_quote, and verifies the prompt string contains the new rounding error audit instructions.
```
</details>

---

## Wave 5 — Advanced Browser Grading

### W5-SSE: Server Grading + SSE Progress

**Origin**: Plan Phase 8
**Size**: Large · **Tier**: Pro

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Implement server-triggered grading with SSE live progress.

See the full specification in docs/plans/stability-decomposition-browser-first.md, Phase 8.

Key deliverables:
1. GradingSessionManager in grader/review/grading_session.py.
2. POST /api/grade, GET /api/grade/status, GET /api/grade/progress (SSE), POST /api/grade/cancel.
3. EventSource-based progress UI with real-time verdicts and progress bars.
```
</details>

---

### W5-ANNOT: PDF Annotation Editing (Option C)

**Origin**: Plan Phase 9
**Size**: Large · **Tier**: Pro

<details>
<summary>📋 Agent Prompt (click to expand)</summary>

```
Implement sidebar-based PDF annotation editing with multi-marker overlay.

See the full specification in docs/plans/stability-decomposition-browser-first.md, Phase 9. DO NOT re-implement click-to-place or drag-to-reposition — they already exist.

Key deliverables:
1. Sidebar X/Y coordinate inputs syncing bidirectionally with click/drag.
2. Render ALL question markers on the current page simultaneously (not just the selected one).
3. Auto-scroll to selected marker with CSS pulse animation.

Guardrails: Changing verdict to incorrect/partial must not allow empty short_reason. needs_review questions must keep the submission band at REVIEW_REQUIRED.
```
</details>

---

## Backlog

| Task ID | Title | Size | Notes |
|:---:|:---|:---:|:---|
| BL-DOCX | Word/TXT/MD Solutions Keys Support | M | Lower friction for instructors. (Note: Student submission DOCX conversion already exists in `discovery.py`; this task is specifically for converting/parsing solution keys). |
| BL-SEARCH | Smart Candidate Search in Downloads | S | Sort by modified date, weight profile name matches higher. |
| BL-VISION | Force Vision Extraction for Math | M | Bypass Tesseract entirely via `force_vision_extraction = true` profile flag. Mainly improves precheck/annotations in unified mode; critical for legacy mode math accuracy. |
| BL-CRITERIA | Structured Scoring Criteria Schema | M | Optional `scoring_criteria` list alongside free-text `scoring_rules`. Adds precision but increases authoring burden — keep opt-in. |
