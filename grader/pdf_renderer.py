from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .location_resolver import clamp, clean_subpart_label, mark_text_for_result

if TYPE_CHECKING:
    import fitz
    from .types import QuestionResult

ANNOTATION_INFO_TITLE = "gradeline"
DEFAULT_ANNOTATION_FONT_SIZE = 24.0
HEADER_FONT_SCALE = 0.66
SUMMARY_TITLE_FONT_SCALE = 0.5
SUMMARY_LINE_FONT_SCALE = 0.5

# Layout-aware mark offsets (relative to page size)
ANNOTATION_OFFSET_X_RATIO = 0.05
ANNOTATION_OFFSET_Y_RATIO = 0.02


def sanitize_subject_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.\-]+", "_", value.strip())
    return cleaned.strip("_") or "x"


def build_annotation_subject(kind: str, **parts: str | int | float) -> str:
    tokens = [sanitize_subject_component(kind)]
    for key, value in parts.items():
        tokens.append(f"{sanitize_subject_component(str(key))}={sanitize_subject_component(str(value))}")
    return "|".join(tokens)


def estimate_text_width(text: str, fontsize: float, minimum: float = 80.0) -> float:
    lines = text.splitlines() or [text]
    max_len = max(len(line) for line in lines)
    return max(minimum, (max_len + 4) * fontsize * 0.58)


def text_annotation_rect_from_baseline(
    page: "fitz.Page",
    x: float,
    y: float,
    text: str,
    fontsize: float,
    min_width: float = 80.0,
    max_width: float = 260.0,
) -> "fitz.Rect":
    import fitz

    rotation = getattr(page, "rotation", 0)
    lines = text.splitlines() or [text]
    num_lines = len(lines)

    estimated = estimate_text_width(text=text, fontsize=fontsize, minimum=min_width)
    effective_max_width = min(max_width, max(min_width, page.rect.width - 48.0))
    width = min(estimated, effective_max_width)
    width = max(width, min(min_width, page.rect.width - 8.0))

    line_height = fontsize * 1.35
    padding = 18.0
    height = max(24.0, num_lines * line_height + padding)

    if rotation != 0:
        p_rot = fitz.Point(x, y) * page.rotation_matrix
        x0_rot = clamp(p_rot.x, 4.0, max(4.0, page.rect.width - width - 4.0))
        y0_rot = clamp(p_rot.y - fontsize - 8.0, 4.0, max(4.0, page.rect.height - height - 4.0))
        rect_rot = fitz.Rect(x0_rot, y0_rot, x0_rot + width, y0_rot + height)
        rect_unrot = rect_rot * (~page.rotation_matrix)
        rect_unrot.normalize()
        return rect_unrot
    else:
        x0 = clamp(x, 4.0, max(4.0, page.rect.width - width - 4.0))
        y0 = clamp(y - fontsize - 8.0, 4.0, max(4.0, page.rect.height - height - 4.0))
        return fitz.Rect(x0, y0, x0 + width, y0 + height)


def is_dark_background(page: "fitz.Page", rect: "fitz.Rect") -> bool:
    try:
        pix = page.get_pixmap(clip=rect)
        samples = pix.samples
        if not samples:
            return False
        n = pix.n
        pixels = len(samples) // n
        if pixels == 0:
            return False
        total_luminance = 0.0
        if n >= 3:
            for i in range(0, len(samples), n):
                r = samples[i]
                g = samples[i + 1]
                b = samples[i + 2]
                total_luminance += 0.299 * r + 0.587 * g + 0.114 * b
        else:
            for i in range(0, len(samples), n):
                val = samples[i]
                total_luminance += val
        avg_luminance = total_luminance / pixels
        return avg_luminance < 128.0
    except Exception:
        return False


def add_movable_freetext_annotation(
    page: "fitz.Page",
    rect: "fitz.Rect",
    text: str,
    fontsize: float,
    color: tuple[float, float, float],
    subject: str,
    fill_color: tuple[float, float, float] | None = None,
    border_color: tuple[float, float, float] | None = None,
) -> None:
    import fitz

    annot = page.add_freetext_annot(
        rect=rect,
        text=text,
        fontsize=fontsize,
        fontname="Helv",
        text_color=color,
        fill_color=fill_color,
        border_color=None,
        border_width=0,
        richtext=False,
    )
    if fill_color is not None:
        try:
            annot.set_opacity(1.0)
        except AttributeError:
            pass
    annot.set_info(
        title=ANNOTATION_INFO_TITLE,
        subject=subject,
        content=text,
    )
    annot.set_rect(rect)
    annot.set_border(width=1 if border_color is not None else 0)
    annot.set_flags((annot.flags or 0) | fitz.PDF_ANNOT_IS_PRINT)
    annot.update(
        fontsize=fontsize,
        fontname="Helv",
        text_color=color,
        border_color=None,
        fill_color=fill_color,
    )
    annot.set_rect(rect)


def find_non_overlapping_rect(
    page: "fitz.Page",
    candidate_rect: "fitz.Rect",
    placed_rects_for_page: list["fitz.Rect"],
    max_nudge_px: float = 450.0,
) -> "fitz.Rect":
    import fitz

    pw, ph = page.rect.width, page.rect.height
    w = min(candidate_rect.width, max(40.0, pw - 8.0))
    h = min(candidate_rect.height, max(20.0, ph - 8.0))
    x0 = clamp(candidate_rect.x0, 4.0, max(4.0, pw - w - 4.0))
    y0 = clamp(candidate_rect.y0, 4.0, max(4.0, ph - h - 4.0))
    current_rect = fitz.Rect(x0, y0, x0 + w, y0 + h)

    # 1. Downward nudging
    total_nudge_y = 0.0
    nudge_step_y = current_rect.height + 4.0

    while total_nudge_y <= max_nudge_px:
        collides = False
        for r in placed_rects_for_page:
            if current_rect.intersects(r):
                collides = True
                break
        if not collides and current_rect.x1 <= pw - 4.0 and current_rect.y1 <= ph - 4.0:
            return current_rect

        next_y0 = current_rect.y0 + nudge_step_y
        if next_y0 + h > ph - 4.0:
            # Try searching upward for open slot
            up_y0 = current_rect.y0 - nudge_step_y
            while up_y0 >= 4.0:
                candidate_up = fitz.Rect(current_rect.x0, up_y0, current_rect.x0 + w, up_y0 + h)
                if not any(candidate_up.intersects(r) for r in placed_rects_for_page):
                    return candidate_up
                up_y0 -= nudge_step_y

            # Try placing leftward
            left_x0 = max(4.0, current_rect.x0 - 160.0)
            if left_x0 >= 4.0 and left_x0 != current_rect.x0:
                current_rect = fitz.Rect(left_x0, current_rect.y0, left_x0 + w, current_rect.y0 + h)
                total_nudge_y += nudge_step_y
                continue
            break
        current_rect = fitz.Rect(current_rect.x0, next_y0, current_rect.x0 + w, next_y0 + h)
        total_nudge_y += nudge_step_y

    # 2. Rightward / Leftward nudging fallback
    current_rect = fitz.Rect(x0, y0, x0 + w, y0 + h)
    total_nudge_x = 0.0
    nudge_step_x = 40.0

    while total_nudge_x <= max_nudge_px:
        collides = False
        for r in placed_rects_for_page:
            if current_rect.intersects(r):
                collides = True
                break
        if not collides and current_rect.x1 <= pw - 4.0 and current_rect.y1 <= ph - 4.0:
            return current_rect

        next_x0 = current_rect.x0 + nudge_step_x
        if next_x0 + w > pw - 4.0:
            next_x0 = max(4.0, current_rect.x0 - nudge_step_x)
        current_rect = fitz.Rect(next_x0, current_rect.y0, next_x0 + w, current_rect.y0 + h)
        total_nudge_x += nudge_step_x

    # Return strictly clamped rect within page boundaries
    final_x0 = clamp(current_rect.x0, 4.0, max(4.0, pw - 44.0))
    w_fit = min(w, max(40.0, pw - final_x0 - 4.0))
    final_y0 = clamp(current_rect.y0, 4.0, max(4.0, ph - h - 4.0))
    return fitz.Rect(final_x0, final_y0, final_x0 + w_fit, final_y0 + h)


def offset_mark_point(
    page: "fitz.Page",
    point: "fitz.Point",
    x_offset: float | None = None,
    y_offset: float | None = None,
) -> "fitz.Point":
    import fitz

    rotation = getattr(page, "rotation", 0)
    if rotation != 0:
        p_rot = point * page.rotation_matrix
        effective_x_offset = x_offset if x_offset is not None else page.rect.width * ANNOTATION_OFFSET_X_RATIO
        effective_y_offset = y_offset if y_offset is not None else -(page.rect.height * ANNOTATION_OFFSET_Y_RATIO)
        x_rot = clamp(p_rot.x + effective_x_offset, 4.0, max(4.0, page.rect.width - 4.0))
        y_rot = clamp(p_rot.y + effective_y_offset, 4.0, max(4.0, page.rect.height - 4.0))
        return fitz.Point(x_rot, y_rot) * (~page.rotation_matrix)
    else:
        effective_x_offset = x_offset if x_offset is not None else page.rect.width * ANNOTATION_OFFSET_X_RATIO
        effective_y_offset = y_offset if y_offset is not None else -(page.rect.height * ANNOTATION_OFFSET_Y_RATIO)

        x = clamp(point.x + effective_x_offset, 4.0, max(4.0, page.rect.width - 4.0))
        y = clamp(point.y + effective_y_offset, 4.0, max(4.0, page.rect.height - 4.0))
        return fitz.Point(x, y)


def insert_mark(
    page: "fitz.Page",
    point: "fitz.Point",
    mark_text: str,
    is_correct: bool,
    question_id: str,
    fontsize: float,
    placed_rects: dict[int, list[fitz.Rect]] | None = None,
) -> None:
    import fitz

    mark_point = offset_mark_point(page=page, point=point)
    fontsize = max(8.0, float(fontsize))
    rect = text_annotation_rect_from_baseline(
        page=page,
        x=mark_point.x,
        y=mark_point.y,
        text=mark_text,
        fontsize=fontsize,
        min_width=140.0,
    )

    if placed_rects is not None:
        page_num = page.number
        placed_list = placed_rects.setdefault(page_num, [])
        rect = find_non_overlapping_rect(page, rect, placed_list)
        placed_list.append(rect)
        mark_point = fitz.Point(rect.x0, rect.y0 + fontsize)

    dark = is_dark_background(page, rect)
    if dark:
        color = (0.0, 0.6, 0.0) if is_correct else (0.8, 0.0, 0.0)
        fill_color = (1.0, 1.0, 1.0)
        border_color = (0.7, 0.7, 0.7)
    else:
        color = (0.0, 0.6, 0.0) if is_correct else (0.8, 0.0, 0.0)
        fill_color = None
        border_color = None

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
        fill_color=fill_color,
        border_color=border_color,
    )


def add_band_header(
    page: "fitz.Page",
    final_band: str,
    dry_run: bool = False,
    fontsize: float = 14.0,
    placed_rects: dict[int, list[fitz.Rect]] | None = None,
) -> None:
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
    if placed_rects is not None:
        placed_rects.setdefault(0, []).append(rect)

    dark = is_dark_background(page, rect)
    if dark:
        color = (0.0, 0.0, 0.0)
        fill_color = (1.0, 1.0, 1.0)
        border_color = (0.7, 0.7, 0.7)
    else:
        color = (0.0, 0.0, 0.0)
        fill_color = None
        border_color = None

    add_movable_freetext_annotation(
        page=page,
        rect=rect,
        text=text,
        fontsize=fontsize,
        color=color,
        subject=build_annotation_subject(
            "header",
            p=page.number + 1,
            band=final_band,
        ),
        fill_color=fill_color,
        border_color=border_color,
    )


def add_fallback_summary(
    page: "fitz.Page",
    unresolved: list,
    result_map: dict[str, QuestionResult],
    title_fontsize: float,
    line_fontsize: float,
    rendered_subparts: set[str] | None = None,
    placed_rects: dict[int, list["fitz.Rect"]] | None = None,
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

    placed_list = placed_rects.setdefault(page.number, []) if placed_rects is not None else []
    if placed_rects is not None:
        title_rect = find_non_overlapping_rect(page, title_rect, placed_list)
        placed_list.append(title_rect)

    dark_title = is_dark_background(page, title_rect)
    if dark_title:
        title_color = (0.1, 0.1, 0.1)
        title_fill = (1.0, 1.0, 1.0)
        title_border = (0.7, 0.7, 0.7)
    else:
        title_color = (0.1, 0.1, 0.1)
        title_fill = None
        title_border = None

    add_movable_freetext_annotation(
        page=page,
        rect=title_rect,
        text=title_text,
        fontsize=title_size,
        color=title_color,
        subject=build_annotation_subject(
            "review_title",
            p=page.number + 1,
        ),
        fill_color=title_fill,
        border_color=title_border,
    )

    curr_y = y + title_rect.height + 4.0
    line_count = 0

    for question in unresolved:
        q_result = result_map.get(question.id)

        if q_result and getattr(q_result, "sub_results", None) and len(q_result.sub_results) > 1:
            for sub_res in q_result.sub_results:
                subpart_label = clean_subpart_label(question.id, sub_res.id)
                full_subpart_key = f"{question.id}.{subpart_label}"

                if rendered_subparts and full_subpart_key in rendered_subparts:
                    continue

                line_count += 1
                verdict = sub_res.verdict
                line_text = mark_text_for_result(question_id=question.id, result=sub_res, subpart_label=subpart_label)
                line_size = max(8.0, float(line_fontsize))
                line_rect = text_annotation_rect_from_baseline(
                    page=page,
                    x=float(x),
                    y=float(curr_y),
                    text=line_text,
                    fontsize=line_size,
                    min_width=150.0,
                )
                if placed_rects is not None:
                    line_rect = find_non_overlapping_rect(page, line_rect, placed_list)
                    placed_list.append(line_rect)

                dark_line = is_dark_background(page, line_rect)
                color = (0.0, 0.6, 0.0) if verdict in ("correct", "rounding_error") else (0.8, 0.0, 0.0)
                line_fill = (1.0, 1.0, 1.0) if dark_line else None
                line_border = (0.7, 0.7, 0.7) if dark_line else None

                add_movable_freetext_annotation(
                    page=page,
                    rect=line_rect,
                    text=line_text,
                    fontsize=line_size,
                    color=color,
                    subject=build_annotation_subject(
                        "review_note",
                        q=full_subpart_key,
                        p=page.number + 1,
                        n=line_count,
                    ),
                    fill_color=line_fill,
                    border_color=line_border,
                )
                curr_y = max(curr_y + line_rect.height + 4.0, line_rect.y1 + 4.0)
            continue

        verdict = q_result.verdict if q_result else "needs_review"

        if q_result is None:
            line_text = f"x Q{question.id}: No result."
        else:
            line_text = mark_text_for_result(question_id=question.id, result=q_result)

        line_count += 1
        line_size = max(8.0, float(line_fontsize))
        line_rect = text_annotation_rect_from_baseline(
            page=page,
            x=float(x),
            y=float(curr_y),
            text=line_text,
            fontsize=line_size,
            min_width=150.0,
        )
        if placed_rects is not None:
            line_rect = find_non_overlapping_rect(page, line_rect, placed_list)
            placed_list.append(line_rect)

        dark_line = is_dark_background(page, line_rect)
        if dark_line:
            color = (0.0, 0.6, 0.0) if verdict in ("correct", "rounding_error") else (0.8, 0.0, 0.0)
            line_fill = (1.0, 1.0, 1.0)
            line_border = (0.7, 0.7, 0.7)
        else:
            color = (0.0, 0.6, 0.0) if verdict in ("correct", "rounding_error") else (0.8, 0.0, 0.0)
            line_fill = None
            line_border = None

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
                n=line_count,
            ),
            fill_color=line_fill,
            border_color=line_border,
        )
        curr_y = max(curr_y + line_rect.height + 4.0, line_rect.y1 + 4.0)
