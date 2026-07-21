from __future__ import annotations

import threading
import inspect
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING
from .extract import extract_pdf_text
from .precheck import regex_precheck
from .score import score_submission
from .types import QuestionResult, SubmissionResult, ExtractedPdf
from .diagnostics import DiagnosticsCollector
from .orchestrator import LEGACY_MODE, UNIFIED_MODE, AGENT_MODE, LOW_CONFIDENCE_THRESHOLD, locator_semaphore, append_error, dedupe_flags, context_cache_flag_message

if TYPE_CHECKING:
    from .orchestrator import GradingConfig

def grade_one_submission(
    unit,
    config: GradingConfig,
    status_update: Callable[[str], None] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pre_extracted: list[ExtractedPdf] | None = None,
) -> SubmissionResult:
    submissions_root = config.submissions_root
    output_dir = config.output_dir
    temp_dir = config.temp_dir
    ocr_char_threshold = config.ocr_char_threshold
    rubric = config.rubric
    solutions_text = config.solutions_text
    solutions_pdf_path = config.solutions_pdf_path
    grade_points = config.grade_points
    grader = config.grader
    grading_mode = config.grading_mode
    agent_type = config.agent_type
    context_cache = config.context_cache
    context_cache_ttl_seconds = config.context_cache_ttl_seconds
    dry_run = config.dry_run
    locator_model = config.locator_model
    annotate_dry_run_marks = config.annotate_dry_run_marks
    extraction_model = config.extraction_model
    gemini_api_key = config.gemini_api_key
    extract_blocks = config.extract_blocks
    diagnostics = config.diagnostics
    rate_limiter = config.rate_limiter

    extracted = []
    extraction_sources: dict[str, str] = {}
    accumulated_error: str | None = None
    global_flags: list[str] = []
    combined_text = ""
    block_registry: dict[str, object] = {}

    if grading_mode == LEGACY_MODE:
        if pre_extracted is not None:
            extracted = pre_extracted
            for item in extracted:
                extraction_sources[item.pdf_path.name] = item.source
        else:
            for pdf_path in unit.pdf_paths:
                if status_update is not None:
                    status_update(f"extracting {pdf_path.name}")
                try:
                    pdf_extract = extract_pdf_text(
                        pdf_path=pdf_path,
                        temp_dir=temp_dir,
                        ocr_char_threshold=ocr_char_threshold,
                        gemini_api_key=gemini_api_key,
                        gemini_model=extraction_model,
                        rate_limiter=rate_limiter,
                        force_vision=getattr(config, "force_vision_extraction", False),
                    )
                except Exception as exc:  # noqa: BLE001
                    extraction_sources[pdf_path.name] = "error"
                    extraction_error = f"Text extraction failed for {pdf_path.name}: {exc}"
                    accumulated_error = append_error(accumulated_error, extraction_error)
                    if "extract_error" not in global_flags:
                        global_flags.append("extract_error")
                    if diagnostics is not None:
                        diagnostics.record(
                            severity="error",
                            code="grading_extract_failed",
                            stage="grading",
                            message=extraction_error,
                            submission_folder=unit.folder_path.name,
                            exc=exc,
                        )
                    continue
                extracted.append(pdf_extract)
                extraction_sources[pdf_path.name] = pdf_extract.source

        combined_text = "\n\n".join(
            f"### FILE: {item.pdf_path.name}\n{item.text}" for item in extracted
        )
        block_registry = {b.id: b for item in extracted for b in item.blocks}
    else:
        # Unified/agent modes send PDFs directly to the model for grading. Optionally
        # run extraction to build the block registry for spatial annotation placement.
        # Disable with extract_blocks=False to skip OCR overhead when not needed.
        extracted_for_precheck = []
        for pdf_path in unit.pdf_paths:
            extraction_sources[pdf_path.name] = "model_vision"

        if extract_blocks:
            if pre_extracted is not None:
                extracted_for_precheck = pre_extracted
                for item in extracted_for_precheck:
                    block_registry.update({b.id: b for b in item.blocks})
            else:
                for pdf_path in unit.pdf_paths:
                    try:
                        pdf_extract = extract_pdf_text(
                            pdf_path=pdf_path,
                            temp_dir=temp_dir,
                            ocr_char_threshold=ocr_char_threshold,
                            gemini_api_key=gemini_api_key,
                            gemini_model=extraction_model,
                            rate_limiter=rate_limiter,
                            force_vision=getattr(config, "force_vision_extraction", False),
                        )
                        block_registry.update({b.id: b for b in pdf_extract.blocks})
                        extracted_for_precheck.append(pdf_extract)
                    except Exception:
                        pass

        if extract_blocks:
            combined_text = "\n\n".join(
                f"### FILE: {item.pdf_path.name}\n{item.text}" for item in extracted_for_precheck
            )

    prechecked_results, hints = regex_precheck(rubric, combined_text)
    questions_to_grade = []
    for q in rubric.questions:
        if q.id in prechecked_results:
            continue
        if q.id in hints:
            note = (
                f"\nNote: The student's final answer appears to match the expected value ({hints[q.id]}). "
                "Focus your evaluation on whether the student showed the required methodology/setup."
            )
            q = replace(q, scoring_rules=q.scoring_rules + note)
        questions_to_grade.append(q)

    if dry_run:
        if status_update is not None:
            status_update("dry-run question statuses")
        question_results = [
            QuestionResult(
                id=question.id,
                verdict="needs_review",
                confidence=0.0,
                short_reason="Dry run mode.",
                evidence_quote="",
                grading_source="dry_run",
            )
            for question in rubric.questions
        ]
        global_flags.append("dry_run")
    else:
        try:
            assert grader is not None
            if not questions_to_grade:
                question_results = []
                model_flags = []
            elif grading_mode == LEGACY_MODE:
                if status_update is not None:
                    status_update(f"grading {len(questions_to_grade)} questions")
                question_results, model_flags = grader.grade_submission(
                    submission_id=unit.folder_path.name,
                    pdf_paths=unit.pdf_paths,
                    combined_text=combined_text,
                    rubric=rubric,
                    solutions_text=solutions_text or "",
                    questions_to_grade=questions_to_grade,
                )
                global_flags.extend(model_flags)
            elif grading_mode == UNIFIED_MODE:
                if status_update is not None:
                    status_update("grading submission in unified mode (this may take up to ~30 seconds)")

                extra_kwargs: dict[str, object] = {}
                if progress_callback is not None:
                    try:
                        sig = inspect.signature(grader.grade_submission_unified)  # type: ignore[attr-defined]
                        if "progress_callback" in sig.parameters:
                            extra_kwargs["progress_callback"] = progress_callback
                    except (ValueError, TypeError, AttributeError):
                        # If we cannot introspect the grader (e.g., fake test grader),
                        # fall back to calling without progress support.
                        pass

                question_results, model_flags = grader.grade_submission_unified(
                    submission_id=unit.folder_path.name,
                    pdf_paths=unit.pdf_paths,
                    rubric=rubric,
                    solutions_pdf_path=solutions_pdf_path,
                    context_cache_enabled=context_cache,
                    context_cache_ttl_seconds=context_cache_ttl_seconds,
                    blocks=list(block_registry.values()) if block_registry else None,
                    questions_to_grade=questions_to_grade,
                    **extra_kwargs,
                )
                global_flags.extend(model_flags)
                if diagnostics is not None:
                    for flag in model_flags:
                        if flag in {
                            "context_cache_lookup_failed",
                            "context_cache_create_failed",
                            "context_cache_bypassed",
                        }:
                            diagnostics.record(
                                severity="warning",
                                code=flag,
                                stage="context_cache",
                                message=context_cache_flag_message(flag),
                                submission_folder=unit.folder_path.name,
                            )
            elif grading_mode == AGENT_MODE:
                if status_update is not None:
                    status_update(f"agentic grading ({agent_type}) {len(questions_to_grade)} questions")
                question_results, model_flags = grader.grade_submission_agent(
                    submission_id=unit.folder_path.name,
                    pdf_paths=unit.pdf_paths,
                    rubric=rubric,
                    solutions_pdf_path=solutions_pdf_path,
                    agent_type=agent_type,
                    questions_to_grade=questions_to_grade,
                )
                global_flags.extend(model_flags)
            else:
                raise ValueError(f"Unsupported grading mode: {grading_mode}")
        except ValueError as exc:
            if grading_mode == UNIFIED_MODE:
                grading_error = f"Unified Gemini schema validation failed: {exc}"
                if diagnostics is not None:
                    diagnostics.record(
                        severity="error",
                        code="unified_schema_invalid",
                        stage="grading",
                        message=grading_error,
                        submission_folder=unit.folder_path.name,
                        exc=exc,
                    )
            else:
                grading_error = f"Gemini grading failed: {exc}"
                if diagnostics is not None:
                    diagnostics.record(
                        severity="error",
                        code="grading_failed",
                        stage="grading",
                        message=grading_error,
                        submission_folder=unit.folder_path.name,
                        exc=exc,
                    )
            question_results = [
                QuestionResult(
                    id=question.id,
                    verdict="needs_review",
                    confidence=0.0,
                    logic_analysis=f"Grading execution encountered an error: {grading_error}",
                    short_reason=grading_error,
                    detail_reason=question.short_note_fail or "Manual grading required due to execution error.",
                    evidence_quote="",
                )
                for question in rubric.questions
            ]
            global_flags.append("grading_error")
            accumulated_error = append_error(accumulated_error, str(exc))
        except Exception as exc:  # noqa: BLE001
            if grading_mode == UNIFIED_MODE:
                grading_error = f"Unified Gemini grading failed: {exc}"
                code = "unified_grading_failed"
            else:
                grading_error = f"Gemini grading failed: {exc}"
                code = "grading_failed"
            if diagnostics is not None:
                diagnostics.record(
                    severity="error",
                    code=code,
                    stage="grading",
                    message=grading_error,
                    submission_folder=unit.folder_path.name,
                    exc=exc,
                )
            question_results = [
                QuestionResult(
                    id=question.id,
                    verdict="needs_review",
                    confidence=0.0,
                    logic_analysis=f"Grading execution encountered an error: {grading_error}",
                    short_reason=grading_error,
                    detail_reason=question.short_note_fail or "Manual grading required due to execution error.",
                    evidence_quote="",
                )
                for question in rubric.questions
            ]
            global_flags.append("grading_error")
            accumulated_error = append_error(accumulated_error, str(exc))

    # Reassemble final question results in original rubric order, and apply diagnostics traces.
    final_question_results = []
    llm_result_map = {res.id: res for res in question_results}

    for q in rubric.questions:
        if q.id in prechecked_results:
            orig = prechecked_results[q.id]
            trace = ("regex_precheck: match",)
            final_qr = QuestionResult(
                id=orig.id,
                verdict=orig.verdict,
                confidence=orig.confidence,
                short_reason=orig.short_reason,
                evidence_quote=orig.evidence_quote,
                logic_analysis=orig.logic_analysis,
                detail_reason=orig.detail_reason,
                coords=orig.coords,
                page_number=orig.page_number,
                source_file=orig.source_file,
                placement_source=orig.placement_source,
                block_id=orig.block_id,
                grading_source=orig.grading_source,
                sub_results=orig.sub_results,
                diagnostics_trace=trace,
            )
            final_question_results.append(final_qr)
        else:
            orig = llm_result_map.get(q.id)
            if orig is None:
                orig = QuestionResult(
                    id=q.id,
                    verdict="needs_review",
                    confidence=0.0,
                    logic_analysis="Grading model did not return an explicit result for this question.",
                    short_reason=q.short_note_fail or "Question omitted by grader.",
                    detail_reason=q.short_note_fail or "Manual evaluation required.",
                    evidence_quote="",
                )

            if dry_run:
                trace = ("dry_run: skipped",)
            else:
                if q.id in hints:
                    precheck_status = "regex_precheck: skipped (requires_work)"
                elif q.expected_answers:
                    precheck_status = "regex_precheck: no match"
                else:
                    precheck_status = "regex_precheck: skipped (no expected_answers)"
                trace = (precheck_status, f"llm_grading: {grading_mode}")

            final_qr = QuestionResult(
                id=orig.id,
                verdict=orig.verdict,
                confidence=orig.confidence,
                short_reason=orig.short_reason,
                evidence_quote=orig.evidence_quote,
                logic_analysis=orig.logic_analysis,
                detail_reason=orig.detail_reason,
                coords=orig.coords,
                page_number=orig.page_number,
                source_file=orig.source_file,
                placement_source=orig.placement_source,
                block_id=orig.block_id,
                grading_source=orig.grading_source,
                sub_results=orig.sub_results,
                diagnostics_trace=trace,
            )
            final_question_results.append(final_qr)

    question_results = final_question_results

    needs_locator = any(result.coords is None for result in question_results)
    if (not dry_run) and locator_model and grader is not None and needs_locator:
        if status_update is not None:
            status_update("locating answer anchors")
        locator_errors: list[str] = []
        try:
            with locator_semaphore:
                candidates = collect_locator_candidates(
                    grader=grader,
                    pdf_paths=unit.pdf_paths,
                    rubric=rubric,
                    locator_model=locator_model,
                    errors_out=locator_errors,
                    diagnostics=diagnostics,
                    submission_folder=unit.folder_path.name,
                )
        except Exception as exc:  # noqa: BLE001
            locator_errors.append(f"Locator invocation failed: {exc}")
            candidates = {}

        question_results = apply_locator_candidates(
            question_results=question_results,
            candidates=candidates,
            pdf_paths=unit.pdf_paths,
        )
        if locator_errors:
            if "locator_error" not in global_flags:
                global_flags.append("locator_error")
            locator_error_text = "; ".join(locator_errors)
            accumulated_error = append_error(accumulated_error, locator_error_text)

    grade_result = score_submission(
        rubric=rubric,
        question_results=question_results,
        grade_points=grade_points,
    )

    return SubmissionResult(
        submission=unit,
        question_results=question_results,
        grade_result=grade_result,
        output_pdf_paths=[],
        extraction_sources=extraction_sources,
        global_flags=dedupe_flags(global_flags),
        block_registry=block_registry,
        error=accumulated_error,
    )

def build_annotation_progress_callback(
    status_update: Callable[[str], None] | None,
    total_questions: int,
) -> Callable[[int, int, str], None] | None:
    if status_update is None:
        return None

    def update(current: int, _: int, question_id: str) -> None:
        status_update(f"annotating question {question_id} ({current}/{total_questions})")

    return update

def build_grading_progress_callback(
    status_update: Callable[[str], None] | None,
    total_questions: int,
) -> Callable[[int, int, str], None] | None:
    """Return a simple callback that formats grading question progress.

    The returned callback matches the same signature used elsewhere: (current, total, question_id).
    If status_update is None, returns None.
    """
    if status_update is None:
        return None

    def update(current: int, _: int, question_id: str) -> None:
        status_update(f"grading question {question_id} ({current}/{total_questions})")

    return update

def collect_locator_candidates(
    grader: Any,
    pdf_paths: list[Path],
    rubric,
    locator_model: str,
    errors_out: list[str],
    diagnostics: DiagnosticsCollector | None = None,
    submission_folder: str | None = None,
) -> dict[str, list[dict]]:
    candidates: dict[str, list[dict]] = {}
    for pdf_path in pdf_paths:
        try:
            per_pdf = grader.locate_answers_for_pdf(
                pdf_path=pdf_path,
                rubric=rubric,
                locator_model=locator_model,
            )
        except Exception as exc:  # noqa: BLE001
            message = f"Locator failed for {pdf_path.name}: {exc}"
            errors_out.append(message)
            if diagnostics is not None:
                diagnostics.record(
                    severity="error",
                    code="locator_failed",
                    stage="locator",
                    message=message,
                    submission_folder=submission_folder,
                    exc=exc,
                )
            continue
        for item in per_pdf:
            qid = str(item.get("id", "")).strip().lower()
            if not qid:
                continue
            candidates.setdefault(qid, []).append(item)
    return candidates

def apply_locator_candidates(
    question_results: list[QuestionResult],
    candidates: dict[str, list[dict]],
    pdf_paths: list[Path],
) -> list[QuestionResult]:
    if not candidates:
        return question_results

    file_rank = {path.name: idx for idx, path in enumerate(pdf_paths)}
    result_map = {result.id: result for result in question_results}

    for question_id, options in candidates.items():
        if question_id not in result_map or not options:
            continue
        # Only fill in coordinates for questions that are currently missing them.
        if result_map[question_id].coords is not None:
            continue
        ordered = sorted(
            options,
            key=lambda item: (
                -float(item.get("confidence", 0.0)),
                file_rank.get(str(item.get("source_file", "")), 10**9),
            ),
        )
        best = ordered[0]
        coords = best.get("coords")
        if not isinstance(coords, tuple) or len(coords) != 2:
            continue
        result_map[question_id] = replace(
            result_map[question_id],
            coords=coords,
            page_number=best.get("page_number"),
            source_file=str(best.get("source_file", "")).strip() or None,
            placement_source="locator_coords",
        )

    return [result_map[result.id] for result in question_results]