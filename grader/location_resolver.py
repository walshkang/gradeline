from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import fitz
    from .types import QuestionResult, TextBlock

# Layout-aware anchor heuristics
ANCHOR_LEFT_MARGIN_RATIO = 0.45
ANCHOR_TOP_MARGIN_RATIO = 0.05
ANCHOR_BOTTOM_MARGIN_RATIO = 0.05


def clean_subpart_label(question_id: str, raw_subpart_id: str) -> str:
    """Normalize subpart label by stripping redundant question ID prefixes."""
    subpart_label = raw_subpart_id
    lower_label = subpart_label.lower()
    qid_lower = question_id.lower()
    for prefix in (f"question {qid_lower}", f"q{qid_lower}", f"question{qid_lower}", "question ", "question", "q.", "q"):
        if lower_label.startswith(prefix):
            subpart_label = subpart_label[len(prefix):].lstrip()
            lower_label = subpart_label.lower()
            break
    if lower_label.startswith(qid_lower):
        subpart_label = subpart_label[len(question_id):].lstrip()
        lower_label = subpart_label.lower()
    subpart_label = subpart_label.lstrip("._- ")
    return subpart_label or raw_subpart_id


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


def proportional_page_fallback(
    page: "fitz.Page",
    question_index: int = 0,
    total_questions: int = 1,
    margin_left: float = 24.0,
    margin_top_ratio: float = 0.10,
    margin_bottom_ratio: float = 0.10,
) -> "fitz.Point":
    """Compute an even-spacing fallback anchor point down the left margin of a page."""
    import fitz

    if total_questions <= 1:
        y_ratio = 0.5
    else:
        norm_idx = clamp(float(question_index), 0.0, float(max(1, total_questions - 1)))
        span = 1.0 - margin_top_ratio - margin_bottom_ratio
        y_ratio = margin_top_ratio + span * ((norm_idx + 0.5) / float(total_questions))

    y_ratio = clamp(y_ratio, 0.05, 0.95)
    x_abs = clamp(margin_left, 4.0, max(4.0, page.rect.width - 4.0))
    y_abs = page.rect.height * y_ratio

    point_rot = fitz.Point(x_abs, y_abs)
    rotation = getattr(page, "rotation", 0)
    if rotation != 0:
        return point_rot * (~page.rotation_matrix)
    return point_rot



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
    question_index: int = 0,
    total_questions: int = 1,
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

                sub_tokens = [
                    f"{parent_id}{sub}",
                    f"{parent_id}.{sub}",
                    f"{parent_id}_{sub}",
                    f"{parent_id}{sub})",
                    f"{parent_id}{sub}.",
                    f"{parent_id}.{sub})",
                    f"({parent_id}{sub})",
                    f"({sub})",
                    f"{sub})",
                    f"{sub}.",
                    f"problem {parent_id}{sub}",
                    f"question {parent_id}{sub}",
                    f"q{parent_id}{sub}",
                    f"q.{parent_id}{sub}",
                ]
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
                        pattern = r"(?i)(?:^|\s|[\(\[\{])" + re.escape(tok) + r"(?:$|\s|[\)\.\:\,\]\}]|\b)"
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
        point = proportional_page_fallback(
            page,
            question_index=question_index,
            total_questions=total_questions,
            margin_left=24.0,
        )
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


def resolve_model_location(
    doc: "fitz.Document",
    pdf_filename: str,
    result: "QuestionResult",
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
                page_area = page.rect.width * page.rect.height
                block_area = block.width * block.height
                # Reject mega-blocks covering >30% of page area and fall back to coords.
                if not (page_area > 0 and (block_area / page_area) > 0.30):
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

    abs_y = (y_norm / 1000.0) * page.rect.height
    abs_x = (x_norm / 1000.0) * page.rect.width

    # When block_registry is present, attempt to re-anchor coords to the nearest matching OCR block
    if block_registry:
        CIRCLED_DIGITS = {"1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤", "6": "⑥", "7": "⑦", "8": "⑧", "9": "⑨", "10": "⑩"}
        qid = str(result.id).strip()
        sub_letter = qid[-1].lower() if len(qid) > 1 and qid[-1].isalpha() else ""
        parent_num = qid[:-1] if sub_letter else qid
        pnum = page_idx + 1

        # Locate parent header block if present
        parent_b = None
        circled_p = CIRCLED_DIGITS.get(parent_num, "")
        pats = []
        if circled_p:
            pats.append(re.escape(circled_p))
        pats.extend([
            rf"(?:^|\s)problem\s*{re.escape(parent_num)}\b",
            rf"(?:^|\s)question\s*{re.escape(parent_num)}\b",
            rf"(?:^|\s)q\.?\s*{re.escape(parent_num)}\b",
            rf"^\s*{re.escape(parent_num)}\.(?!\d)",
            rf"^\s*{re.escape(parent_num)}[\)\:]",
        ])
        for b in block_registry.values():
            text = b.text.strip()
            for p in pats:
                if re.search(p, text, re.IGNORECASE):
                    parent_b = b
                    break
            if parent_b:
                break

        candidates = []
        for b in block_registry.values():
            if parent_b:
                if b.page < parent_b.page:
                    continue
                if b.page == parent_b.page and b.top < parent_b.top - 5.0:
                    continue
            text = b.text.strip().lower()
            clean_t = text.lstrip(" ([\t")
            is_sub_match = sub_letter and (
                clean_t.startswith(f"{sub_letter})")
                or clean_t.startswith(f"{sub_letter}.")
                or clean_t.startswith(f"({sub_letter})")
                or clean_t.startswith(f"{qid.lower()}")
                or clean_t.startswith(f"{parent_num}.{sub_letter}")
                or clean_t.startswith(f"{parent_num}{sub_letter}")
            )
            is_parent_match = (parent_b and b.id == parent_b.id)

            if is_sub_match or is_parent_match:
                page_diff = abs(b.page - pnum)
                dist = abs(b.top - abs_y) + (page_diff * 1000.0)
                prio = 3 if is_sub_match else 1
                candidates.append((prio, dist, b))

        if candidates:
            candidates.sort(key=lambda c: (-c[0], c[1]))
            matched_b = candidates[0][2]
            abs_x = max(15.0, matched_b.left - 10.0)
            abs_y = matched_b.top
            page_idx = max(0, min(len(doc) - 1, matched_b.page - 1))
            page = doc[page_idx]

    x = clamp(abs_x, 4.0, max(4.0, page.rect.width - 4.0))
    y = clamp(abs_y, 4.0, max(4.0, page.rect.height - 4.0))
    point_rot = fitz.Point(x, y)
    rotation = getattr(page, "rotation", 0)
    if rotation != 0:
        point = point_rot * (~page.rotation_matrix)
    else:
        point = point_rot
    return page_idx, point, (y_norm, x_norm)


def mark_text_for_result(question_id: str, result: "QuestionResult", *, subpart_label: str | None = None) -> str:
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
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped + "…"
