from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .types import QuestionResult, RubricConfig, SubmissionUnit, TextBlock

ANNOTATION_INFO_TITLE = "gradeline"
DEFAULT_ANNOTATION_FONT_SIZE = 24.0
HEADER_FONT_SCALE = 0.66
SUMMARY_TITLE_FONT_SCALE = 0.5
SUMMARY_LINE_FONT_SCALE = 0.5

# Layout-aware anchor heuristics
ANCHOR_LEFT_MARGIN_RATIO = 0.4
ANCHOR_TOP_MARGIN_RATIO = 0.10
ANCHOR_BOTTOM_MARGIN_RATIO = 0.10

# Layout-aware mark offsets (relative to page size)
ANNOTATION_OFFSET_X_RATIO = 0.05
ANNOTATION_OFFSET_Y_RATIO = 0.02


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
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[list[Path], list[QuestionResult]]:
    import fitz  # Lazy import for testability without dependency.

    result_map = {item.id: item for item in question_results}
    rendered: set[str] = set()
    output_paths: list[Path] = []
    placement_details: dict[str, dict[str, object | None]] = {}
    render_question_marks = should_render_question_marks(
        dry_run=dry_run,
        annotate_dry_run_marks=annotate_dry_run_marks,
    )

    for pdf_path in submission.pdf_paths:
        rel_path = pdf_path.relative_to(submissions_root)
        out_path = output_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(pdf_path)
        try:
            # Explicitly disable NeedAppearances. If this is True, many PDF viewers 
            # (including macOS Preview and Acrobat) will render both the static appearance 
            # stream AND their own interpretation of the annotation, causing double-text.
            doc.need_appearances(False)

            if len(doc) == 0:
                doc.save(out_path)
                output_paths.append(out_path)
                continue

            if render_question_marks:
                question_fontsize = max(8.0, float(annotation_font_size))
                for question in rubric.questions:
                    q_result = result_map.get(question.id)
                    if q_result is None:
                        continue
                    if question.id in rendered:
                        continue
                    if progress_callback is not None:
                        progress_callback(len(rendered) + 1, len(rubric.questions), question.id)

                    model_location = resolve_model_location(
                        doc=doc,
                        pdf_filename=pdf_path.name,
                        result=q_result,
                        block_registry=block_registry,
                    )
                    if model_location is not None:
                        # resolve_model_location may return (page_idx, point, normalized_coords)
                        # or (page_idx, point, normalized_coords, placement_source)
                        if len(model_location) == 3:
                            page_idx, point, normalized_coords = model_location
                            placement_source = q_result.placement_source or "model_coords"
                        else:
                            page_idx, point, normalized_coords, resolver_placement_source = model_location
                            placement_source = q_result.placement_source or resolver_placement_source
                    else:
                        anchor = find_anchor_in_doc(
                            doc=doc,
                            question_id=question.id,
                            label_patterns=question.label_patterns,
                            explicit_tokens=question.anchor_tokens,
                        )
                        if anchor is None:
                            continue
                        page_idx, point = anchor
                        normalized_coords = point_to_normalized(doc[page_idx], point)
                        placement_source = q_result.placement_source or "local_anchor"

                    mark_text = mark_text_for_result(question_id=question.id, result=q_result)
                    insert_mark(
                        doc[page_idx],
                        point,
                        mark_text=mark_text,
                        is_correct=(q_result.verdict == "correct"),
                        question_id=question.id,
                        fontsize=question_fontsize,
                    )
                    rendered.add(question.id)
                    placement_details[question.id] = {
                        "placement_source": placement_source,
                        "source_file": pdf_path.name,
                        "page_number": page_idx + 1,
                        "coords": normalized_coords,
                    }

            if pdf_path == submission.pdf_paths[0]:
                header_fontsize = max(8.0, float(annotation_font_size) * HEADER_FONT_SCALE)
                add_band_header(doc[0], final_band=final_band, dry_run=dry_run, fontsize=header_fontsize)

            doc.save(out_path)
            output_paths.append(out_path)
        finally:
            doc.close()

    unresolved = [q for q in rubric.questions if q.id not in rendered]
    if render_question_marks and unresolved and output_paths:
        doc = fitz.open(output_paths[0])
        try:
            doc.need_appearances(False)
            title_fontsize = max(8.0, float(annotation_font_size) * SUMMARY_TITLE_FONT_SCALE)
            line_fontsize = max(8.0, float(annotation_font_size) * SUMMARY_LINE_FONT_SCALE)
            add_fallback_summary(
                doc[0],
                unresolved=unresolved,
                result_map=result_map,
                title_fontsize=title_fontsize,
                line_fontsize=line_fontsize,
            )
            doc.saveIncr()
        finally:
            doc.close()
        for question in unresolved:
            placement_details[question.id] = {
                "placement_source": "summary_fallback",
                "source_file": output_paths[0].name,
                "page_number": 1,
                "coords": None,
            }

    if dry_run and not annotate_dry_run_marks:
        for question in rubric.questions:
            placement_details[question.id] = {
                "placement_source": "dry_run_header_only",
                "source_file": output_paths[0].name if output_paths else None,
                "page_number": 1 if output_paths else None,
                "coords": None,
            }

    updated_results: list[QuestionResult] = []
    for result in question_results:
        details = placement_details.get(result.id)
        if details is None:
            updated_results.append(result)
            continue
        coords_value = details.get("coords")
        coords = coords_value if isinstance(coords_value, tuple) else None
        page_number = details.get("page_number")
        source_file = details.get("source_file")
        placement_source = details.get("placement_source")
        updated_results.append(
            replace(
                result,
                coords=coords if coords is not None else result.coords,
                page_number=page_number if isinstance(page_number, int) else result.page_number,
                source_file=source_file if isinstance(source_file, str) else result.source_file,
                placement_source=placement_source if isinstance(placement_source, str) else result.placement_source,
            )
        )

    return output_paths, updated_results


def resolve_model_location(
    doc: "fitz.Document",
    pdf_filename: str,
    result: QuestionResult,
    block_registry: dict[str, "TextBlock"] | None = None,
):
    import fitz

    # Prefer block-based placement if the result references a block id.
    block_id = getattr(result, "block_id", None)
    if block_id:
        if block_registry and block_id in block_registry:
            block = block_registry[block_id]
            page_idx = block.page - 1
            # Validate page index exists in the document; otherwise fall through to coords handling.
            if 0 <= page_idx < len(doc):
                page = doc[page_idx]
                x = block.left + (block.width / 2.0)
                y = block.top
                point = fitz.Point(x, y)
                normalized_coords = point_to_normalized(page, point)
                # Return placement_source as an extra element so callers can honor it.
                return page_idx, point, normalized_coords, "block_id"
        # If block_id was provided but not found in the registry, fall through to coords handling.

    if result.coords is None:
        return None

    if result.source_file:
        expected = Path(result.source_file).name
        actual = Path(pdf_filename).name
        if expected != actual:
            return None

    page_idx = 0
    if isinstance(result.page_number, int) and 1 <= result.page_number <= len(doc):
        page_idx = result.page_number - 1
    elif len(doc) == 0:
        return None

    page = doc[page_idx]
    y_norm, x_norm = result.coords
    y_norm = clamp(y_norm, 0.0, 1000.0)
    x_norm = clamp(x_norm, 0.0, 1000.0)
    x = clamp((x_norm / 1000.0) * page.rect.width, 4.0, max(4.0, page.rect.width - 4.0))
    y = clamp((y_norm / 1000.0) * page.rect.height, 4.0, max(4.0, page.rect.height - 4.0))
    point = fitz.Point(x, y)
    return page_idx, point, (y_norm, x_norm)


def should_render_question_marks(dry_run: bool, annotate_dry_run_marks: bool) -> bool:
    return (not dry_run) or annotate_dry_run_marks


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def point_to_normalized(page: "fitz.Page", point: "fitz.Point") -> tuple[float, float]:
    if page.rect.width <= 0 or page.rect.height <= 0:
        return (0.0, 0.0)
    y = clamp((point.y / page.rect.height) * 1000.0, 0.0, 1000.0)
    x = clamp((point.x / page.rect.width) * 1000.0, 0.0, 1000.0)
    return (y, x)


def build_anchor_tokens(question_id: str, label_patterns: list[str], explicit_tokens: list[str]) -> list[str]:
    tokens: list[str] = []
    tokens.extend(explicit_tokens)
    tokens.extend(
        [
            f"{question_id})",
            f"{question_id}.",
            f"({question_id})",
            f"{question_id.upper()})",
            f"{question_id.upper()}.",
        ]
    )
    for pattern in label_patterns:
        if is_literal_pattern(pattern):
            literal = strip_regex_markers(pattern)
            if literal:
                tokens.append(literal)
    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        norm = token.strip()
        if not norm:
            continue
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(norm)
    return deduped


def is_literal_pattern(pattern: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9\s\.\:\-\(\)\[\]\_]+", pattern or "") is not None


def strip_regex_markers(pattern: str) -> str:
    return pattern.replace(r"\b", "").replace("^", "").replace("$", "").strip()


def find_anchor_in_doc(
    doc: "fitz.Document",
    question_id: str,
    label_patterns: list[str],
    explicit_tokens: list[str],
):
    import fitz

    tokens = build_anchor_tokens(question_id, label_patterns, explicit_tokens)
    candidates_by_page: dict[int, list["fitz.Rect"]] = {}

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        raw_rects: list["fitz.Rect"] = []
        for token in tokens:
            rects = page.search_for(token)
            if rects:
                raw_rects.extend(rects)
        if not raw_rects:
            continue

        left_limit = page.rect.width * ANCHOR_LEFT_MARGIN_RATIO
        top_limit = page.rect.height * ANCHOR_TOP_MARGIN_RATIO
        bottom_limit = page.rect.height * (1.0 - ANCHOR_BOTTOM_MARGIN_RATIO)

        filtered = [
            rect
            for rect in raw_rects
            if rect.x0 < left_limit and rect.y0 >= top_limit and rect.y1 <= bottom_limit
        ]
        use_rects = filtered or raw_rects
        candidates_by_page[page_idx] = use_rects

    if not candidates_by_page:
        return None

    # Prefer the latest page in the document that has candidates, then the lowest match on that page.
    best_page_idx = max(candidates_by_page.keys())
    page_rects = candidates_by_page[best_page_idx]
    best_rect = max(page_rects, key=lambda r: r.y0)

    page = doc[best_page_idx]
    point = fitz.Point(best_rect.x1 + 6, best_rect.y0 + 10)
    return best_page_idx, point


def mark_text_for_result(question_id: str, result: QuestionResult) -> str:
    symbol = "✓" if result.verdict == "correct" else "x"
    if result.verdict == "correct":
        return f"{symbol} Q{question_id}"
    reason = compact_reason(result.short_reason, max_chars=42) or "Review manually."
    return f"{symbol} Q{question_id}: {reason}"


def compact_reason(text: str, max_chars: int = 42) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    clipped = cleaned[:max_chars].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    return clipped or cleaned[:max_chars].rstrip()


def sanitize_subject_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.\-]+", "_", value.strip())
    return cleaned.strip("_") or "x"


def build_annotation_subject(kind: str, **parts: str | int | float) -> str:
    tokens = [sanitize_subject_component(kind)]
    for key, value in parts.items():
        tokens.append(f"{sanitize_subject_component(str(key))}={sanitize_subject_component(str(value))}")
    return "|".join(tokens)


def estimate_text_width(text: str, fontsize: float, minimum: float = 80.0) -> float:
    return max(minimum, (len(text) + 2) * fontsize * 0.58)


def text_annotation_rect_from_baseline(
    page: "fitz.Page",
    x: float,
    y: float,
    text: str,
    fontsize: float,
    min_width: float = 80.0,
) -> "fitz.Rect":
    import fitz

    width = min(
        estimate_text_width(text=text, fontsize=fontsize, minimum=min_width),
        max(24.0, page.rect.width - 8.0),
    )
    # FreeText annotations render with extra inner padding in Preview.
    height = max(20.0, fontsize + 12.0)
    x0 = clamp(x, 4.0, max(4.0, page.rect.width - width - 4.0))
    y0 = clamp(y - fontsize, 4.0, max(4.0, page.rect.height - height - 4.0))
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def add_movable_freetext_annotation(
    page: "fitz.Page",
    rect: "fitz.Rect",
    text: str,
    fontsize: float,
    color: tuple[float, float, float],
    subject: str,
) -> None:
    import fitz

    # Create FreeText annotation. PyMuPDF sets the content and default appearance.
    annot = page.add_freetext_annot(
        rect=rect,
        text=text,
        fontsize=fontsize,
        fontname="Helv",
        text_color=color,
        fill_color=None,
        border_color=None,
        border_width=0,
    )
    # Set metadata. We skip 'content' here as it's already set by add_freetext_annot;
    # redundant setting can cause some viewers (like macOS Preview) to render a "ghost" text box.
    annot.set_info(
        title=ANNOTATION_INFO_TITLE,
        subject=subject,
    )
    annot.set_border(width=0)
    # Ensure annotation is printable and visible.
    annot.set_flags((annot.flags or 0) | fitz.PDF_ANNOT_IS_PRINT)
    # Generate the Appearance Stream (/AP). This is the "static" version of the annotation.
    # We explicitly do NOT use doc.need_appearances(True) as it causes double-printing in many apps.
    annot.update(
        fontsize=fontsize,
        fontname="Helv",
        text_color=color,
        border_color=None,
        fill_color=None,
    )


def insert_mark(
    page: "fitz.Page",
    point: "fitz.Point",
    mark_text: str,
    is_correct: bool,
    question_id: str,
    fontsize: float,
) -> None:
    mark_point = offset_mark_point(page=page, point=point)
    fontsize = max(8.0, float(fontsize))
    color = (0.0, 0.55, 0.0) if is_correct else (0.8, 0.0, 0.0)
    rect = text_annotation_rect_from_baseline(
        page=page,
        x=mark_point.x,
        y=mark_point.y,
        text=mark_text,
        fontsize=fontsize,
        min_width=140.0,
    )
    subject = build_annotation_subject(
        "question_mark",
        q=question_id,
        p=page.number + 1,
        x=int(mark_point.x),
        y=int(mark_point.y),
    )
    add_movable_freetext_annotation(
        page=page,
        rect=rect,
        text=mark_text,
        fontsize=fontsize,
        color=color,
        subject=subject,
    )


def offset_mark_point(
    page: "fitz.Page",
    point: "fitz.Point",
    x_offset: float | None = None,
    y_offset: float | None = None,
) -> "fitz.Point":
    import fitz

    # Default to layout-aware offsets relative to page size.
    effective_x_offset = x_offset if x_offset is not None else page.rect.width * ANNOTATION_OFFSET_X_RATIO
    effective_y_offset = y_offset if y_offset is not None else -(page.rect.height * ANNOTATION_OFFSET_Y_RATIO)

    x = clamp(point.x + effective_x_offset, 4.0, max(4.0, page.rect.width - 4.0))
    y = clamp(point.y + effective_y_offset, 4.0, max(4.0, page.rect.height - 4.0))
    return fitz.Point(x, y)


def add_band_header(page: "fitz.Page", final_band: str, dry_run: bool = False, fontsize: float = 14.0) -> None:
    text = f"Grade: {final_band}"
    if dry_run:
        text = f"Dry Run - {final_band} (no per-question marks)"
    x = max(24, page.rect.width - 320)
    y = 36
    fontsize = max(8.0, float(fontsize))
    rect = text_annotation_rect_from_baseline(
        page=page,
        x=float(x),
        y=float(y),
        text=text,
        fontsize=fontsize,
        min_width=220.0,
    )
    add_movable_freetext_annotation(
        page=page,
        rect=rect,
        text=text,
        fontsize=fontsize,
        color=(0.0, 0.0, 0.0),
        subject=build_annotation_subject(
            "header",
            p=page.number + 1,
            band=final_band,
        ),
    )


def add_fallback_summary(
    page: "fitz.Page",
    unresolved: list,
    result_map: dict[str, QuestionResult],
    title_fontsize: float,
    line_fontsize: float,
) -> None:
    x = max(24, page.rect.width - 230)
    y = 72
    title_text = "Review Notes:"
    title_size = max(8.0, float(title_fontsize))
    title_rect = text_annotation_rect_from_baseline(
        page=page,
        x=float(x),
        y=float(y),
        text=title_text,
        fontsize=title_size,
        min_width=120.0,
    )
    add_movable_freetext_annotation(
        page=page,
        rect=title_rect,
        text=title_text,
        fontsize=title_size,
        color=(0.1, 0.1, 0.1),
        subject=build_annotation_subject(
            "review_title",
            p=page.number + 1,
        ),
    )

    for idx, question in enumerate(unresolved, start=1):
        q_result = result_map.get(question.id)
        verdict = q_result.verdict if q_result else "needs_review"
        color = (0.0, 0.55, 0.0) if verdict == "correct" else (0.8, 0.0, 0.0)
        if q_result is None:
            line_text = f"x Q{question.id}: No result."
        else:
            line_text = mark_text_for_result(question_id=question.id, result=q_result)
        line_size = max(8.0, float(line_fontsize))
        line_rect = text_annotation_rect_from_baseline(
            page=page,
            x=float(x),
            y=float(y + (idx * 14)),
            text=line_text,
            fontsize=line_size,
            min_width=150.0,
        )
        add_movable_freetext_annotation(
            page=page,
            rect=line_rect,
            text=line_text,
            fontsize=line_size,
            color=color,
            subject=build_annotation_subject(
                "review_note",
                q=question.id,
                p=page.number + 1,
                n=idx,
            ),
        )
