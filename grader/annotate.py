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
    try:
        fitz.TOOLS.mupdf_display_errors(False)
    except AttributeError:
        pass


    result_map = {item.id: item for item in question_results}
    placed_rects: dict[int, list[fitz.Rect]] = {}
    rendered: set[str] = set()
    rendered_subparts: set[str] = set()
    output_paths: list[Path] = []
    placement_details: dict[str, dict[str, object | None]] = {}
    single_pdf = len(submission.pdf_paths) == 1
    render_question_marks = should_render_question_marks(
        dry_run=dry_run,
        annotate_dry_run_marks=annotate_dry_run_marks,
    )

    for pdf_path in submission.pdf_paths:
        placed_rects.clear()
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

            if pdf_path == submission.pdf_paths[0]:
                header_fontsize = max(8.0, float(annotation_font_size) * HEADER_FONT_SCALE)
                add_band_header(
                    doc[0],
                    final_band=final_band,
                    dry_run=dry_run,
                    fontsize=header_fontsize,
                    placed_rects=placed_rects,
                )

            if render_question_marks:
                question_fontsize = max(8.0, float(annotation_font_size))
                total_questions = len(rubric.questions)
                for q_idx, question in enumerate(rubric.questions):
                    q_result = result_map.get(question.id)
                    if q_result is None:
                        continue
                    if question.id in rendered:
                        continue
                    if progress_callback is not None:
                        progress_callback(len(rendered) + 1, len(rubric.questions), question.id)

                    fallback_y_ratio = (q_idx + 0.5) / total_questions if total_questions > 0 else 0.5

                    if not single_pdf and q_result.source_file:
                        if Path(q_result.source_file).name.lower() != pdf_path.name.lower():
                            continue

                    if getattr(q_result, "sub_results", None) and len(q_result.sub_results) > 1:
                        # Render individual marks for each sub-part
                        all_subparts_rendered = True
                        parent_loc_resolved = False
                        parent_page_idx, parent_point = None, None
                        missing_count = 0

                        for sub_result in q_result.sub_results:
                            subpart_label = sub_result.id

                            # strip "q", "q.", "question "
                            lower_label = subpart_label.lower()
                            for prefix in ("question ", "question", "q.", "q"):
                                if lower_label.startswith(prefix):
                                    subpart_label = subpart_label[len(prefix):].lstrip()
                                    break

                            if subpart_label.lower().startswith(question.id.lower()):
                                subpart_label = subpart_label[len(question.id):].lstrip("._- ")
                            subpart_label = subpart_label or sub_result.id
                            full_subpart_key = f"{question.id}.{subpart_label}"

                            if full_subpart_key in rendered_subparts:
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
                                # Fallback 1: finding anchor for the subpart
                                sub_anchor = find_anchor_in_doc(
                                    doc=doc,
                                    question_id=sub_result.id,
                                    label_patterns=[],
                                    explicit_tokens=[f"{subpart_label})", f"{subpart_label}."],
                                    fallback_y_ratio=fallback_y_ratio,
                                    block_registry=block_registry,
                                )
                                if sub_anchor:
                                    sub_page_idx, sub_point = sub_anchor
                                else:
                                    # Fallback 2: parent location or parent anchor
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
                                    placed_rects=placed_rects,
                                )
                                rendered_subparts.add(full_subpart_key)
                            else:
                                all_subparts_rendered = False

                        if all_subparts_rendered:
                            rendered.add(question.id)

                        # Record placement for the first sub-part with valid coords for audit
                        for sub_result in q_result.sub_results:
                            if sub_result.coords is not None:
                                placement_details[question.id] = {
                                    "placement_source": "subpart_model_coords",
                                    "source_file": sub_result.source_file or pdf_path.name,
                                    "page_number": getattr(sub_result, "page_number", None),
                                    "coords": sub_result.coords,
                                }
                                break

                        continue

                    model_location = resolve_model_location(
                        doc=doc,
                        pdf_filename=pdf_path.name,
                        result=q_result,
                        block_registry=block_registry,
                        ignore_source_file=single_pdf,
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
                            fallback_y_ratio=fallback_y_ratio,
                            block_registry=block_registry,
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
                        is_correct=(q_result.verdict in ("correct", "rounding_error")),
                        question_id=question.id,
                        fontsize=question_fontsize,
                        placed_rects=placed_rects,
                    )
                    rendered.add(question.id)
                    placement_details[question.id] = {
                        "placement_source": placement_source,
                        "source_file": pdf_path.name,
                        "page_number": page_idx + 1,
                        "coords": normalized_coords,
                    }

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
                rendered_subparts=rendered_subparts,
                placed_rects=placed_rects,
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
    ignore_source_file: bool = False,
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
                x = max(15.0, block.left - 10.0)
                y = block.top
                point_rot = fitz.Point(x, y)
                rotation = getattr(page, "rotation", 0)
                if rotation != 0:
                    point = point_rot * (~page.rotation_matrix)
                else:
                    point = point_rot
                normalized_coords = point_to_normalized(page, point)
                # Return placement_source as an extra element so callers can honor it.
                return page_idx, point, normalized_coords, "block_id"
        # If block_id was provided but not found in the registry, fall through to coords handling.

    if result.coords is None:
        return None

    if result.source_file and not ignore_source_file:
        expected = Path(result.source_file).name.lower()
        actual = Path(pdf_filename).name.lower()
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
    # Reject coordinates suspiciously close to the corner — likely a model default/guess.
    if y_norm < 5.0 and x_norm < 5.0:
        return None
    x = clamp((x_norm / 1000.0) * page.rect.width, 4.0, max(4.0, page.rect.width - 4.0))
    y = clamp((y_norm / 1000.0) * page.rect.height, 4.0, max(4.0, page.rect.height - 4.0))
    point_rot = fitz.Point(x, y)
    rotation = getattr(page, "rotation", 0)
    if rotation != 0:
        point = point_rot * (~page.rotation_matrix)
    else:
        point = point_rot
    return page_idx, point, (y_norm, x_norm)


def should_render_question_marks(dry_run: bool, annotate_dry_run_marks: bool) -> bool:
    return (not dry_run) or annotate_dry_run_marks


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def point_to_normalized(page: "fitz.Page", point: "fitz.Point") -> tuple[float, float]:
    if page.rect.width <= 0 or page.rect.height <= 0:
        return (0.0, 0.0)
    rotation = getattr(page, "rotation", 0)
    if rotation != 0:
        p_rot = point * page.rotation_matrix
        y = clamp((p_rot.y / page.rect.height) * 1000.0, 0.0, 1000.0)
        x = clamp((p_rot.x / page.rect.width) * 1000.0, 0.0, 1000.0)
    else:
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
    fallback_y_ratio: float = 0.5,
    block_registry: dict[str, "TextBlock"] | None = None,
):
    import fitz

    tokens = build_anchor_tokens(question_id, label_patterns, explicit_tokens)
    
    explicit_set = set(explicit_tokens)
    
    def get_token_priority(tok: str) -> int:
        if tok in explicit_set:
            return 3
        
        # Determine if the token is a generic fallback: e.g. "1.", "1)", "(1)", "[1]", "1:"
        clean = tok.strip().lower()
        qid = question_id.strip().lower()
        generic_patterns = {qid, f"{qid}.", f"{qid})", f"({qid})", f"[{qid}]", f"{qid}:"}
        
        qid_up = qid.upper()
        generic_patterns.update({qid_up, f"{qid_up}.", f"{qid_up})", f"({qid_up})", f"[{qid_up}]", f"{qid_up}:"})
        
        if clean in generic_patterns:
            return 1
        return 2

    # Map page_idx -> (highest_priority_on_page, list_of_rects_for_that_priority)
    page_matches: dict[int, tuple[int, list["fitz.Rect"]]] = {}
    max_priority_found = 0

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        left_limit = page.rect.width * ANCHOR_LEFT_MARGIN_RATIO
        top_limit = page.rect.height * ANCHOR_TOP_MARGIN_RATIO
        bottom_limit = page.rect.height * (1.0 - ANCHOR_BOTTOM_MARGIN_RATIO)

        page_rects_by_priority: dict[int, list["fitz.Rect"]] = {3: [], 2: [], 1: []}

        for token in tokens:
            rects = page.search_for(token)
            if not rects:
                continue

            prio = get_token_priority(token)
            filtered = [
                rect
                for rect in rects
                if rect.x0 < left_limit and rect.y0 >= top_limit and rect.y1 <= bottom_limit
            ]
            use_rects = filtered or rects
            page_rects_by_priority[prio].extend(use_rects)

        # Find the highest priority category that has matches on this page
        page_highest_priority = 0
        for prio in (3, 2, 1):
            if page_rects_by_priority[prio]:
                page_highest_priority = prio
                break

        if page_highest_priority > 0:
            page_matches[page_idx] = (page_highest_priority, page_rects_by_priority[page_highest_priority])
            if page_highest_priority > max_priority_found:
                max_priority_found = page_highest_priority

    if max_priority_found == 0:
        if len(doc) == 0:
            return None

        # Search OCR block_registry before falling back to proportional ratios on scanned image PDFs
        if block_registry:
            CIRCLED_DIGITS = {"1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤", "6": "⑥", "7": "⑦", "8": "⑧", "9": "⑨", "10": "⑩"}
            blocks = list(block_registry.values())
            
            # Subquestion or main question matching logic
            sub_match = re.match(r"^(\d+)\.?([a-zA-Z])$", question_id)
            target_block = None
            if sub_match:
                parent_id, sub = sub_match.group(1), sub_match.group(2).lower()
                circled = CIRCLED_DIGITS.get(parent_id, "")
                parent_pats = [rf"(?:^|\s)problem\s*{re.escape(parent_id)}\b", rf"(?:^|\s)question\s*{re.escape(parent_id)}\b", rf"(?:^|\s)q\.?\s*{re.escape(parent_id)}\b", rf"^\s*{re.escape(parent_id)}[\.\)\:]"]
                if circled:
                    parent_pats.insert(0, re.escape(circled))
                
                parent_b = None
                for b in blocks:
                    text = b.text.strip()
                    for p in parent_pats:
                        if re.search(p, text, re.IGNORECASE):
                            parent_b = b
                            break
                    if parent_b:
                        break
                
                next_parent_b = None
                if parent_b:
                    for q_next in range(int(parent_id) + 1, 20):
                        circled_next = CIRCLED_DIGITS.get(str(q_next), "")
                        next_pats = [rf"(?:^|\s)problem\s*{q_next}\b", rf"(?:^|\s)question\s*{q_next}\b", rf"^\s*{q_next}[\.\)\:]"]
                        if circled_next:
                            next_pats.insert(0, re.escape(circled_next))
                        for b in blocks:
                            text = b.text.strip()
                            for p in next_pats:
                                if re.search(p, text, re.IGNORECASE):
                                    next_parent_b = b
                                    break
                            if next_parent_b:
                                break
                        if next_parent_b:
                            break

                sub_tokens = [f"{parent_id}{sub}", f"{parent_id}.{sub}", f"{sub})", f"{sub}.", f"({sub})"]
                candidates = []
                for b in blocks:
                    if parent_b:
                        if b.page < parent_b.page:
                            continue
                        if b.page == parent_b.page and b.top < parent_b.top - 5:
                            continue
                    if next_parent_b:
                        if b.page > next_parent_b.page:
                            continue
                        if b.page == next_parent_b.page and b.top >= next_parent_b.top - 5:
                            continue
                    
                    text = b.text.strip()
                    for tok in sub_tokens:
                        pattern = r"(?i)(?:^|\s|\b)" + re.escape(tok) + r"(?:$|\s|\b|\)|\.|\:)"
                        if re.search(pattern, text):
                            is_exact = f"{parent_id}{sub}" in tok.lower() or f"{parent_id}.{sub}" in tok.lower()
                            prio = 3 if is_exact else 2
                            candidates.append((prio, b.page, b.top, b))
                            break
                if candidates:
                    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
                    target_block = candidates[0][3]
            else:
                # Main question block matching
                circled = CIRCLED_DIGITS.get(question_id, "")
                pats = [rf"(?:^|\s)problem\s*{re.escape(question_id)}\b", rf"(?:^|\s)question\s*{re.escape(question_id)}\b", rf"(?:^|\s)q\.?\s*{re.escape(question_id)}\b", rf"^\s*{re.escape(question_id)}[\.\)\:]"]
                if circled:
                    pats.insert(0, re.escape(circled))
                for b in blocks:
                    text = b.text.strip()
                    for p in pats:
                        if re.search(p, text, re.IGNORECASE):
                            target_block = b
                            break
                    if target_block:
                        break

            if target_block:
                page_idx = target_block.page - 1
                if 0 <= page_idx < len(doc):
                    x = max(15.0, target_block.left - 10.0)
                    y = target_block.top
                    point_rot = fitz.Point(x, y)
                    rotation = getattr(doc[page_idx], "rotation", 0)
                    if rotation != 0:
                        point = point_rot * (~doc[page_idx].rotation_matrix)
                    else:
                        point = point_rot
                    return page_idx, point

        # Empty un-OCR'd pages (0 text) or scanned image PDFs (<300 chars text with images) 
        # fallback to proportional page anchors. Digital text PDFs with content return None 
        # so unfound questions drop cleanly into Page 1 review notes.
        has_images = any(len(p.get_images()) > 0 for p in doc)
        total_text_len = sum(len(p.get_text().strip()) for p in doc)
        is_scanned_or_empty = (total_text_len == 0) or (has_images and total_text_len < 300)
        if not is_scanned_or_empty:
            return None

        page_idx = 0
        if len(doc) > 1:
            num_match = re.search(r"\d+", question_id)
            if num_match:
                q_num = int(num_match.group())
                page_idx = min(len(doc) - 1, max(0, q_num - 1))
            else:
                page_idx = min(len(doc) - 1, int(fallback_y_ratio * len(doc)))

        page = doc[page_idx]
        x_rot = max(24.0, page.rect.width - 150.0)
        y_rot = page.rect.height * fallback_y_ratio
        point_rot = fitz.Point(x_rot, y_rot)
        rotation = getattr(page, "rotation", 0)
        if rotation != 0:
            point = point_rot * (~page.rotation_matrix)
        else:
            point = point_rot
        return page_idx, point

    # Filter to pages that match at the highest priority level found in the document
    candidate_pages = [
        page_idx
        for page_idx, (prio, _) in page_matches.items()
        if prio == max_priority_found
    ]

    # Guard against generic anchor tokens (e.g. "8.") matching headers/footers on Page 1 for high Q numbers
    if len(candidate_pages) > 1 and max_priority_found == 1:
        num_match = re.search(r"\d+", question_id)
        if num_match and int(num_match.group()) >= 5:
            later_pages = [p for p in candidate_pages if p > 0]
            if later_pages:
                candidate_pages = later_pages

    # Prefer the earliest candidate page
    best_page_idx = min(candidate_pages)
    _, page_rect = page_matches[best_page_idx]
    
    # On that page, prefer the lowest match (largest y0)
    best_rect = max(page_rect, key=lambda r: r.y0)
    page = doc[best_page_idx]
    point = fitz.Point(best_rect.x1 + 6, best_rect.y0 + 10)
    return best_page_idx, point


def mark_text_for_result(question_id: str, result: QuestionResult, *, subpart_label: str | None = None) -> str:
    display_id = f"{question_id}.{subpart_label}" if subpart_label else question_id
    if result.verdict == "correct":
        return f"✓ Q{display_id}"
    if result.verdict == "rounding_error":
        return f"✓ Q{display_id} ≈"
    reason = compact_reason(result.short_reason, max_chars=42)
    if reason:
        return f"x Q{display_id}: {reason}"
    return f"x Q{display_id}"


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
) -> "fitz.Rect":
    import fitz

    rotation = getattr(page, "rotation", 0)
    lines = text.splitlines() or [text]
    num_lines = len(lines)

    width = min(
        estimate_text_width(text=text, fontsize=fontsize, minimum=min_width),
        max(24.0, page.rect.width - 8.0),
    )
    # Provide generous height including top/bottom padding + per-line height
    # so descenders (g, p, q, y) and bottom lines are never cut off.
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
                g = samples[i+1]
                b = samples[i+2]
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

    # Create FreeText annotation. PyMuPDF sets the content and default appearance.
    # Note: We keep richtext=False because richtext=True overrides text_color to default black in many viewers.
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
            # Set opacity to 1.0 (opaque) so dark/black page backgrounds don't bleed through and ruin text contrast.
            annot.set_opacity(1.0)
        except AttributeError:
            pass
    # Set metadata. We skip 'content' here as it's already set by add_freetext_annot;
    # redundant setting can cause some viewers (like macOS Preview) to render a "ghost" text box.
    annot.set_info(
        title=ANNOTATION_INFO_TITLE,
        subject=subject,
        content=text,
    )
    annot.set_rect(rect)
    annot.set_border(width=1 if border_color is not None else 0)
    # Ensure annotation is printable and visible.
    annot.set_flags((annot.flags or 0) | fitz.PDF_ANNOT_IS_PRINT)
    # Generate the Appearance Stream (/AP). This is the "static" version of the annotation.
    # We explicitly do NOT use doc.need_appearances(True) as it causes double-printing in many apps.
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
    max_nudge_px: float = 200.0,
) -> "fitz.Rect":
    import fitz

    pw, ph = page.rect.width, page.rect.height
    w = min(candidate_rect.width, pw - 8.0)
    h = min(candidate_rect.height, ph - 8.0)
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
            found_up = False
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
    w_fit = min(w, max(40.0, pw - 8.0))
    final_x0 = clamp(current_rect.x0, 4.0, max(4.0, pw - w_fit - 4.0))
    final_y0 = clamp(current_rect.y0, 4.0, max(4.0, ph - h - 4.0))
    return fitz.Rect(final_x0, final_y0, final_x0 + w_fit, final_y0 + h)


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

    # Detect background brightness at the location of the mark to prioritize readability
    dark = is_dark_background(page, rect)
    if dark:
        color = (0.0, 0.6, 0.0) if is_correct else (0.8, 0.0, 0.0)  # vibrant green / red
        fill_color = (1.0, 1.0, 1.0)  # mostly opaque white box
        border_color = (0.7, 0.7, 0.7)  # light gray border
    else:
        color = (0.0, 0.6, 0.0) if is_correct else (0.8, 0.0, 0.0)  # vibrant green / red
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

    # Detect background brightness for the header
    dark = is_dark_background(page, rect)
    if dark:
        color = (0.0, 0.0, 0.0)  # black
        fill_color = (1.0, 1.0, 1.0)  # mostly opaque white box
        border_color = (0.7, 0.7, 0.7)  # light gray border
    else:
        color = (0.0, 0.0, 0.0)  # black
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

    # Detect background brightness for title
    dark_title = is_dark_background(page, title_rect)
    if dark_title:
        title_color = (0.1, 0.1, 0.1)  # dark charcoal
        title_fill = (1.0, 1.0, 1.0)  # mostly opaque white box
        title_border = (0.7, 0.7, 0.7)  # light gray border
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

        # Handle questions with sub_results individually
        if q_result and getattr(q_result, "sub_results", None) and len(q_result.sub_results) > 1:
            for sub_res in q_result.sub_results:
                subpart_label = sub_res.id
                lower_label = subpart_label.lower()
                for prefix in ("question ", "question", "q.", "q"):
                    if lower_label.startswith(prefix):
                        subpart_label = subpart_label[len(prefix):].lstrip()
                        break
                if subpart_label.lower().startswith(question.id.lower()):
                    subpart_label = subpart_label[len(question.id):].lstrip("._- ")
                subpart_label = subpart_label or sub_res.id
                full_subpart_key = f"{question.id}.{subpart_label}"

                if rendered_subparts and full_subpart_key in rendered_subparts:
                    continue  # Skip subparts already marked on student pages

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

        # Detect background brightness for each line
        dark_line = is_dark_background(page, line_rect)
        if dark_line:
            color = (0.0, 0.6, 0.0) if verdict in ("correct", "rounding_error") else (0.8, 0.0, 0.0)
            line_fill = (1.0, 1.0, 1.0)  # mostly opaque white box
            line_border = (0.7, 0.7, 0.7)  # light gray border
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

