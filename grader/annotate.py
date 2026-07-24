from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .annotation_state import AnnotationSession
from .location_resolver import (
    ANCHOR_BOTTOM_MARGIN_RATIO,
    ANCHOR_LEFT_MARGIN_RATIO,
    ANCHOR_TOP_MARGIN_RATIO,
    build_anchor_tokens,
    clamp,
    clean_subpart_label,
    compact_reason,
    find_anchor_in_doc,
    find_answer_anchor_in_doc,
    is_literal_pattern,
    mark_text_for_result,
    point_to_normalized,
    proportional_page_fallback,
    resolve_model_location,
    should_render_question_marks,
    strip_regex_markers,
)
from .pdf_renderer import (
    ANNOTATION_INFO_TITLE,
    ANNOTATION_OFFSET_X_RATIO,
    ANNOTATION_OFFSET_Y_RATIO,
    DEFAULT_ANNOTATION_FONT_SIZE,
    HEADER_FONT_SCALE,
    SUMMARY_LINE_FONT_SCALE,
    SUMMARY_TITLE_FONT_SCALE,
    add_band_header,
    add_fallback_summary,
    add_movable_freetext_annotation,
    build_annotation_subject,
    estimate_text_width,
    find_non_overlapping_rect,
    insert_mark,
    is_dark_background,
    offset_mark_point,
    sanitize_subject_component,
    text_annotation_rect_from_baseline,
)
from .types import QuestionResult, RubricConfig, SubmissionUnit, TextBlock


def annotate_submission_pdfs(
    submission: SubmissionUnit,
    rubric: RubricConfig,
    question_results: list[QuestionResult],
    *,
    block_registry: dict[str, "TextBlock"] | None = None,
    output_dir: Path,
    submissions_root: Path,
    final_band: str,
    dry_run: bool = False,
    annotate_dry_run_marks: bool = False,
    annotation_font_size: float = DEFAULT_ANNOTATION_FONT_SIZE,
    annotation_mode: str = "answer_inline",
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[list[Path], list[QuestionResult]]:
    import fitz  # Lazy import for testability without dependency.

    try:
        fitz.TOOLS.mupdf_display_errors(False)
    except AttributeError:
        pass

    session = AnnotationSession(
        result_map={item.id: item for item in question_results}
    )
    single_pdf = len(submission.pdf_paths) == 1
    render_question_marks = should_render_question_marks(
        dry_run=dry_run,
        annotate_dry_run_marks=annotate_dry_run_marks,
    )

    for pdf_path in submission.pdf_paths:
        _annotate_single_pdf(
            pdf_path=pdf_path,
            submission=submission,
            rubric=rubric,
            session=session,
            block_registry=block_registry,
            output_dir=output_dir,
            submissions_root=submissions_root,
            final_band=final_band,
            dry_run=dry_run,
            single_pdf=single_pdf,
            render_question_marks=render_question_marks,
            annotation_font_size=annotation_font_size,
            annotation_mode=annotation_mode,
            progress_callback=progress_callback,
        )

    _append_unresolved_summary(
        rubric=rubric,
        session=session,
        render_question_marks=render_question_marks,
        annotation_font_size=annotation_font_size,
    )

    if dry_run and not annotate_dry_run_marks:
        for question in rubric.questions:
            session.record_placement(
                question.id,
                {
                    "placement_source": "dry_run_header_only",
                    "source_file": session.output_paths[0].name if session.output_paths else None,
                    "page_number": 1 if session.output_paths else None,
                    "coords": None,
                },
            )

    updated_results = session.finalize_updated_results(question_results)
    return session.output_paths, updated_results


def _annotate_single_pdf(
    pdf_path: Path,
    submission: SubmissionUnit,
    rubric: RubricConfig,
    session: AnnotationSession,
    *,
    block_registry: dict[str, "TextBlock"] | None,
    output_dir: Path,
    submissions_root: Path,
    final_band: str,
    dry_run: bool,
    single_pdf: bool,
    render_question_marks: bool,
    annotation_font_size: float,
    annotation_mode: str = "answer_inline",
    progress_callback: Callable[[int, int, str], None] | None,
) -> None:
    import fitz

    session.clear_placed_rects()
    rel_path = pdf_path.relative_to(submissions_root)
    out_path = output_dir / rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    try:
        doc.need_appearances(False)

        if len(doc) == 0:
            doc.save(out_path)
            session.output_paths.append(out_path)
            return

        if pdf_path == submission.pdf_paths[0]:
            header_fontsize = max(8.0, float(annotation_font_size) * HEADER_FONT_SCALE)
            add_band_header(
                doc[0],
                final_band=final_band,
                dry_run=dry_run,
                fontsize=header_fontsize,
                placed_rects=session.placed_rects,
            )

        if render_question_marks and annotation_mode != "header_summary_only":
            question_fontsize = max(8.0, float(annotation_font_size))
            total_questions = len(rubric.questions)
            for q_idx, question in enumerate(rubric.questions):
                _process_question_annotation(
                    doc=doc,
                    pdf_path=pdf_path,
                    question=question,
                    q_idx=q_idx,
                    total_questions=total_questions,
                    rubric=rubric,
                    session=session,
                    block_registry=block_registry,
                    single_pdf=single_pdf,
                    question_fontsize=question_fontsize,
                    annotation_mode=annotation_mode,
                    progress_callback=progress_callback,
                )

        doc.save(out_path)
        session.output_paths.append(out_path)
    finally:
        doc.close()


def _process_question_annotation(
    doc: fitz.Document,
    pdf_path: Path,
    question: Any,
    q_idx: int,
    total_questions: int,
    rubric: RubricConfig,
    session: AnnotationSession,
    *,
    block_registry: dict[str, "TextBlock"] | None,
    single_pdf: bool,
    question_fontsize: float,
    annotation_mode: str = "answer_inline",
    progress_callback: Callable[[int, int, str], None] | None,
) -> None:
    q_result = session.result_map.get(question.id)
    if q_result is None or session.is_rendered(question.id):
        return

    if progress_callback is not None:
        progress_callback(len(session.rendered) + 1, len(rubric.questions), question.id)

    fallback_y_ratio = (q_idx + 0.5) / total_questions if total_questions > 0 else 0.5

    if not single_pdf and q_result.source_file:
        if Path(q_result.source_file).name.lower() != pdf_path.name.lower():
            return

    if getattr(q_result, "sub_results", None) and len(q_result.sub_results) > 1:
        _process_subparts_annotation(
            doc=doc,
            pdf_path=pdf_path,
            question=question,
            q_result=q_result,
            fallback_y_ratio=fallback_y_ratio,
            session=session,
            block_registry=block_registry,
            single_pdf=single_pdf,
            question_fontsize=question_fontsize,
            question_index=q_idx,
            total_questions=total_questions,
            annotation_mode=annotation_mode,
        )
    else:
        _process_single_question_annotation(
            doc=doc,
            pdf_path=pdf_path,
            question=question,
            q_result=q_result,
            fallback_y_ratio=fallback_y_ratio,
            session=session,
            block_registry=block_registry,
            single_pdf=single_pdf,
            question_fontsize=question_fontsize,
            question_index=q_idx,
            total_questions=total_questions,
            annotation_mode=annotation_mode,
        )


def _process_subparts_annotation(
    doc: fitz.Document,
    pdf_path: Path,
    question: Any,
    q_result: QuestionResult,
    fallback_y_ratio: float,
    session: AnnotationSession,
    *,
    block_registry: dict[str, "TextBlock"] | None,
    single_pdf: bool,
    question_fontsize: float,
    question_index: int = 0,
    total_questions: int = 1,
    annotation_mode: str = "answer_inline",
) -> None:
    if annotation_mode == "header_summary_only":
        return

    all_subparts_rendered = True
    parent_loc_resolved = False
    parent_page_idx, parent_point = None, None
    missing_count = 0

    for sub_result in q_result.sub_results:
        subpart_label = clean_subpart_label(question.id, sub_result.id)
        full_subpart_key = f"{question.id}.{subpart_label}"

        if session.is_subpart_rendered(full_subpart_key):
            continue

        sub_model_location = resolve_model_location(
            doc=doc,
            pdf_filename=pdf_path.name,
            result=sub_result,
            block_registry=block_registry,
            ignore_source_file=single_pdf,
        )

        sub_page_idx, sub_point = None, None

        if sub_model_location is not None:
            sub_page_idx = sub_model_location[0]
            sub_point = sub_model_location[1]
        else:
            sub_anchor = find_anchor_in_doc(
                doc=doc,
                question_id=sub_result.id,
                label_patterns=[],
                explicit_tokens=[f"{subpart_label})", f"{subpart_label}."],
                fallback_y_ratio=fallback_y_ratio,
                block_registry=block_registry,
                question_index=question_index,
                total_questions=total_questions,
            )
            if sub_anchor:
                sub_page_idx, sub_point = sub_anchor
            else:
                if not parent_loc_resolved:
                    parent_loc = resolve_model_location(
                        doc=doc,
                        pdf_filename=pdf_path.name,
                        result=q_result,
                        block_registry=block_registry,
                        ignore_source_file=single_pdf,
                    )
                    if parent_loc:
                        parent_page_idx, parent_point = parent_loc[0], parent_loc[1]
                    else:
                        parent_anchor = find_anchor_in_doc(
                            doc=doc,
                            question_id=question.id,
                            label_patterns=question.label_patterns,
                            explicit_tokens=question.anchor_tokens,
                            fallback_y_ratio=fallback_y_ratio,
                            block_registry=block_registry,
                            question_index=question_index,
                            total_questions=total_questions,
                        )
                        if parent_anchor:
                            parent_page_idx, parent_point = parent_anchor
                    parent_loc_resolved = True

                if parent_page_idx is not None and parent_point is not None:
                    import fitz

                    sub_page_idx = parent_page_idx
                    sub_point = fitz.Point(parent_point.x, parent_point.y + (missing_count * 38))
                    missing_count += 1

        if sub_page_idx is not None and sub_point is not None:
            anchor_location = (sub_page_idx, sub_point)
            if annotation_mode == "answer_inline":
                ans_loc = find_answer_anchor_in_doc(
                    doc=doc,
                    question_id=sub_result.id,
                    q_result=sub_result,
                    anchor_location=anchor_location,
                    block_registry=block_registry,
                )
                if ans_loc is not None:
                    sub_page_idx, sub_point = ans_loc[0], ans_loc[1]
            elif annotation_mode == "right_margin":
                right_x = max(10.0, doc[sub_page_idx].rect.width - 80.0)
                sub_point = fitz.Point(right_x, sub_point.y)

            sub_mark_text = mark_text_for_result(
                question_id=question.id,
                result=sub_result,
                subpart_label=subpart_label,
            )
            sub_fontsize = max(8.0, question_fontsize * 0.85)
            insert_mark(
                doc[sub_page_idx],
                sub_point,
                mark_text=sub_mark_text,
                is_correct=(sub_result.verdict in ("correct", "rounding_error")),
                question_id=full_subpart_key,
                fontsize=sub_fontsize,
                placed_rects=session.placed_rects,
            )
            session.mark_subpart_rendered(full_subpart_key)
        else:
            all_subparts_rendered = False

    if all_subparts_rendered:
        session.mark_rendered(question.id)

    for sub_result in q_result.sub_results:
        if sub_result.coords is not None:
            session.record_placement(
                question.id,
                {
                    "placement_source": "subpart_model_coords",
                    "source_file": sub_result.source_file or pdf_path.name,
                    "page_number": getattr(sub_result, "page_number", None),
                    "coords": sub_result.coords,
                },
            )
            break


def _process_single_question_annotation(
    doc: fitz.Document,
    pdf_path: Path,
    question: Any,
    q_result: QuestionResult,
    fallback_y_ratio: float,
    session: AnnotationSession,
    *,
    block_registry: dict[str, "TextBlock"] | None,
    single_pdf: bool,
    question_fontsize: float,
    question_index: int = 0,
    total_questions: int = 1,
    annotation_mode: str = "answer_inline",
) -> None:
    if annotation_mode == "header_summary_only":
        return

    model_location = resolve_model_location(
        doc=doc,
        pdf_filename=pdf_path.name,
        result=q_result,
        block_registry=block_registry,
        ignore_source_file=single_pdf,
    )
    anchor_location = None
    if model_location is not None:
        page_idx, point = model_location[0], model_location[1]
        anchor_location = (page_idx, point)
        placement_source = q_result.placement_source or "model_coords"
    else:
        anchor = find_anchor_in_doc(
            doc=doc,
            question_id=question.id,
            label_patterns=question.label_patterns,
            explicit_tokens=question.anchor_tokens,
            fallback_y_ratio=fallback_y_ratio,
            block_registry=block_registry,
            question_index=question_index,
            total_questions=total_questions,
        )
        if anchor is None:
            return
        anchor_location = anchor
        placement_source = q_result.placement_source or "local_anchor"

    if annotation_mode == "answer_inline":
        ans_loc = find_answer_anchor_in_doc(
            doc=doc,
            question_id=question.id,
            q_result=q_result,
            anchor_location=anchor_location,
            block_registry=block_registry,
        )
        if ans_loc is not None:
            page_idx, point, placement_source = ans_loc
        else:
            page_idx, point = anchor_location
    elif annotation_mode == "right_margin":
        page_idx, header_point = anchor_location
        right_x = max(10.0, doc[page_idx].rect.width - 80.0)
        point = fitz.Point(right_x, header_point.y)
        placement_source = "right_margin"
    else:
        page_idx, point = anchor_location

    normalized_coords = point_to_normalized(doc[page_idx], point)

    mark_text = mark_text_for_result(question_id=question.id, result=q_result)
    insert_mark(
        doc[page_idx],
        point,
        mark_text=mark_text,
        is_correct=(q_result.verdict in ("correct", "rounding_error")),
        question_id=question.id,
        fontsize=question_fontsize,
        placed_rects=session.placed_rects,
    )
    session.mark_rendered(question.id)
    session.record_placement(
        question.id,
        {
            "placement_source": placement_source,
            "source_file": pdf_path.name,
            "page_number": page_idx + 1,
            "coords": normalized_coords,
        },
    )


def _append_unresolved_summary(
    rubric: RubricConfig,
    session: AnnotationSession,
    *,
    render_question_marks: bool,
    annotation_font_size: float,
) -> None:
    import fitz

    unresolved = [q for q in rubric.questions if not session.is_rendered(q.id)]
    if render_question_marks and unresolved and session.output_paths:
        doc = fitz.open(session.output_paths[0])
        try:
            doc.need_appearances(False)
            title_fontsize = max(8.0, float(annotation_font_size) * SUMMARY_TITLE_FONT_SCALE)
            line_fontsize = max(8.0, float(annotation_font_size) * SUMMARY_LINE_FONT_SCALE)
            add_fallback_summary(
                doc[0],
                unresolved=unresolved,
                result_map=session.result_map,
                title_fontsize=title_fontsize,
                line_fontsize=line_fontsize,
                rendered_subparts=session.rendered_subparts,
                placed_rects=session.placed_rects,
            )
            doc.saveIncr()
        finally:
            doc.close()

        for question in unresolved:
            session.record_placement(
                question.id,
                {
                    "placement_source": "summary_fallback",
                    "source_file": session.output_paths[0].name,
                    "page_number": 1,
                    "coords": None,
                },
            )


# Re-export location resolution & rendering functions for 100% backward compatibility
__all__ = [
    "AnnotationSession",
    "annotate_submission_pdfs",
    # Renderer re-exports
    "ANNOTATION_INFO_TITLE",
    "DEFAULT_ANNOTATION_FONT_SIZE",
    "HEADER_FONT_SCALE",
    "SUMMARY_TITLE_FONT_SCALE",
    "SUMMARY_LINE_FONT_SCALE",
    "ANNOTATION_OFFSET_X_RATIO",
    "ANNOTATION_OFFSET_Y_RATIO",
    "sanitize_subject_component",
    "build_annotation_subject",
    "estimate_text_width",
    "text_annotation_rect_from_baseline",
    "is_dark_background",
    "add_movable_freetext_annotation",
    "find_non_overlapping_rect",
    "offset_mark_point",
    "insert_mark",
    "add_band_header",
    "add_fallback_summary",
    # Location resolver re-exports
    "ANCHOR_LEFT_MARGIN_RATIO",
    "ANCHOR_TOP_MARGIN_RATIO",
    "ANCHOR_BOTTOM_MARGIN_RATIO",
    "clean_subpart_label",
    "should_render_question_marks",
    "clamp",
    "point_to_normalized",
    "build_anchor_tokens",
    "strip_regex_markers",
    "is_literal_pattern",
    "mark_text_for_result",
    "compact_reason",
    "find_anchor_in_doc",
    "resolve_model_location",
    "proportional_page_fallback",
]
