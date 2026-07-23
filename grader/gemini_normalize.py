from __future__ import annotations

import re
from typing import Any

from .cost import TokenUsage
from .gemini_schemas import (
    DETAIL_REASON_MAX_CHARS,
    DETAIL_REASON_MAX_WORDS,
    SHORT_REASON_MAX_CHARS,
    SHORT_REASON_MAX_WORDS,
)
from .types import JsonDict, QuestionResult, RubricConfig


def canonical_id(qid: str) -> str:
    """Canonicalize a question ID by stripping prefixes, whitespace, and punctuation.

    Examples:
      '2.a' -> '2a'
      '2-a' -> '2a'
      'Q2.a' -> '2a'
      'question 3' -> '3'
    """
    s = str(qid).strip().lower()
    for prefix in ("question ", "question", "q.", "q"):
        if s.startswith(prefix) and len(s) > len(prefix) and (s[len(prefix)].isdigit() or s[len(prefix)] in ".-_ "):
            s = s[len(prefix):].strip()
            break
    return re.sub(r"[^a-z0-9]", "", s)


def match_subparts_to_parent(parent_id: str, raw_item: dict) -> bool:
    """Return True if raw_item represents a sub-part of parent_id.

    Matches patterns like:
      parent="1" → "1.a", "1.b", "1.1", "1_a", "1a" in raw_item["id"]
      parent="4" → "4.a", "4.b", "4.1", "q4.a", "Q4.b" in raw_item["id"]
      parent="3" → raw_item["id"]="part c of question 3"
      parent="3" → raw_item["id"]="c", with "question 3" in raw_item["logic_analysis"]
    """
    raw_id = str(raw_item.get("id", "")).strip()
    if not raw_id:
        return False

    parent = parent_id.strip().lower()
    raw = raw_id.lower()

    # 1. Strip common prefixes: "q", "q.", "question", "question "
    for prefix in ("question ", "question", "q.", "q"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].lstrip()
            break

    if raw == parent or (canonical_id(raw) and canonical_id(raw) == canonical_id(parent)):
        return True  # Exact or canonical match

    # 2. Check if raw starts with parent followed by a separator (e.g., "1.a" or "1a")
    if raw.startswith(parent):
        remainder = raw[len(parent):]
        if remainder:
            # The first character after parent_id must be a separator or letter
            # to avoid matching parent="1" to raw="10"
            first_char = remainder[0]
            if first_char in ('.', '_', '-', ' ') or first_char.isalpha():
                return True

    # 3. Check for standalone parent_id in raw ID string (e.g. "part c of question 3")
    # We want to match parent as a standalone word (e.g. word boundary on both sides,
    # or preceded by q/question, but not part of another number like "30").
    pattern = rf"\b(q|question\s*)?{re.escape(parent)}\b"
    if re.search(pattern, raw):
        return True

    # 4. Context scan: if the raw ID is very generic (e.g., has no digits other than parent digits),
    # search the content fields (logic_analysis, evidence_quote, short_reason) for clear references
    # to this parent question (e.g., "question 3", "q3", "q.3").
    raw_digits = "".join(c for c in raw if c.isdigit())
    parent_digits = "".join(c for c in parent if c.isdigit())
    is_generic = all(d in parent_digits for d in raw_digits)
    if is_generic:
        content_fields = [
            str(raw_item.get("logic_analysis", "")),
            str(raw_item.get("evidence_quote", "")),
            str(raw_item.get("short_reason", "")),
        ]
        combined_content = " ".join(content_fields).lower()
        content_pattern = rf"\b(q|question|q\.)\s*{re.escape(parent)}\b"
        if re.search(content_pattern, combined_content):
            return True

    return False


def aggregate_subpart_verdicts(sub_verdicts: list[str]) -> str:
    """Aggregate multiple sub-part verdicts into a single parent verdict.

    Rules (ordered by priority):
    - If ANY sub-part is needs_review → needs_review
    - If ALL are correct → correct
    - If ALL are correct or rounding_error (with ≥1 rounding_error) → rounding_error
    - If ALL are incorrect → incorrect
    - Otherwise → partial
    """
    if not sub_verdicts:
        return "needs_review"

    verdict_set = set(sub_verdicts)

    if "needs_review" in verdict_set:
        return "needs_review"
    if verdict_set == {"correct"}:
        return "correct"
    if verdict_set <= {"correct", "rounding_error"}:
        return "rounding_error"
    if verdict_set == {"incorrect"}:
        return "incorrect"
    return "partial"


def normalize_model_response(payload: JsonDict, rubric: RubricConfig, token_usage: TokenUsage | None = None) -> JsonDict:
    if token_usage is None and isinstance(payload.get("token_usage"), dict):
        token_usage = TokenUsage.from_dict(payload.get("token_usage"))

    questions_raw = payload.get("questions")
    if not isinstance(questions_raw, list):
        raise ValueError("Gemini response must include 'questions' list.")

    question_map: dict[str, JsonDict] = {}
    canonical_map: dict[str, JsonDict] = {}
    for item in questions_raw:
        if isinstance(item, dict) and "id" in item:
            qid = str(item["id"]).strip().lower()
            question_map[qid] = item
            cid = canonical_id(qid)
            if cid and cid not in canonical_map:
                canonical_map[cid] = item

    # Group sub-question IDs under their rubric parent ID
    parent_subparts: dict[str, list[JsonDict]] = {}
    for question in rubric.questions:
        parent_id = question.id.strip().lower()
        if parent_id in question_map or canonical_id(parent_id) in canonical_map:
            continue  # Direct or canonical match exists, no need to search sub-parts
        subs = []
        for raw_id, raw_item in question_map.items():
            if match_subparts_to_parent(parent_id, raw_item):
                subs.append(raw_item)
        if subs:
            parent_subparts[parent_id] = subs

    normalized_questions: list[QuestionResult] = []
    for question in rubric.questions:
        qid_lower = question.id.strip().lower()
        raw = question_map.get(qid_lower) or canonical_map.get(canonical_id(question.id))
        sub_items = parent_subparts.get(qid_lower)

        if raw is None and sub_items is None:
            # No match at all — flag for review
            fallback_reason = question.short_note_fail or "Question omitted by model during grading."
            normalized_questions.append(
                QuestionResult(
                    id=question.id,
                    verdict="needs_review",
                    confidence=0.0,
                    logic_analysis="The model did not return an explicit evaluation for this question node.",
                    short_reason=fallback_reason,
                    detail_reason="Manual review required to verify whether this answer is present in the submission.",
                    evidence_quote="",
                    token_usage=token_usage,
                )
            )
            continue

        if raw is not None:
            # Direct match — process as before
            verdict = normalize_verdict(raw.get("verdict"))
            confidence = normalize_confidence(raw.get("confidence"))
            logic_analysis = str(raw.get("logic_analysis", "")).strip()
            short_reason, detail_reason = normalize_feedback(
                verdict=verdict,
                raw_short_reason=str(raw.get("short_reason", "")).strip()[:500],
                raw_detail_reason=str(raw.get("detail_reason", "")).strip()[:900],
                fallback_fail_note=question.short_note_fail,
            )
            evidence_quote = str(raw.get("evidence_quote", "")).strip()[:500]
            coords = parse_coords_0_to_1000(raw.get("coords"))
            page_number = parse_page_number(raw.get("page_number") or raw.get("page"))
            source_file = str(raw.get("source_file", "")).strip() or None
            block_id = str(raw.get("block_id", "")).strip() or None
            normalized_questions.append(
                QuestionResult(
                    id=question.id,
                    verdict=verdict,
                    confidence=confidence,
                    logic_analysis=logic_analysis,
                    short_reason=short_reason,
                    detail_reason=detail_reason,
                    evidence_quote=evidence_quote,
                    coords=coords,
                    page_number=page_number,
                    source_file=source_file,
                    block_id=block_id,
                    token_usage=token_usage,
                )
            )
            continue

        # Sub-part aggregation path
        sub_verdicts = [normalize_verdict(s.get("verdict")) for s in sub_items]
        aggregated_verdict = aggregate_subpart_verdicts(sub_verdicts)
        aggregated_confidence = min(
            normalize_confidence(s.get("confidence")) for s in sub_items
        )

        # Build logic_analysis by concatenating sub-part analyses
        analysis_parts = []
        for s in sub_items:
            sid = str(s.get("id", "")).strip()
            analysis = str(s.get("logic_analysis", "")).strip()
            if analysis:
                analysis_parts.append(f"[{sid}] {analysis}")
        aggregated_logic = "\n".join(analysis_parts)

        # Pick short_reason from the first failing sub-part
        first_failing = next(
            (s for s in sub_items if normalize_verdict(s.get("verdict")) not in ("correct", "rounding_error")),
            sub_items[0],
        )
        raw_short = str(first_failing.get("short_reason", "")).strip()[:500]
        raw_detail = str(first_failing.get("detail_reason", "")).strip()[:900]
        short_reason, detail_reason = normalize_feedback(
            verdict=aggregated_verdict,
            raw_short_reason=raw_short,
            raw_detail_reason=raw_detail,
            fallback_fail_note=question.short_note_fail,
        )

        # Pick coords from the first failing sub-part (or first sub-part)
        coord_source = first_failing
        coords = parse_coords_0_to_1000(coord_source.get("coords"))
        page_number = parse_page_number(coord_source.get("page_number") or coord_source.get("page"))
        source_file = str(coord_source.get("source_file", "")).strip() or None
        block_id = str(coord_source.get("block_id", "")).strip() or None

        # Evidence: concatenate from all sub-parts
        evidence_parts = [str(s.get("evidence_quote", "")).strip() for s in sub_items if s.get("evidence_quote")]
        evidence_quote = " | ".join(evidence_parts)[:500]

        sub_question_results = []
        for s in sub_items:
            sub_verdict = normalize_verdict(s.get("verdict"))
            sub_conf = normalize_confidence(s.get("confidence"))
            sub_raw_short = str(s.get("short_reason", "")).strip()[:500]
            sub_raw_detail = str(s.get("detail_reason", "")).strip()[:900]
            sub_short, sub_detail = normalize_feedback(
                verdict=sub_verdict,
                raw_short_reason=sub_raw_short,
                raw_detail_reason=sub_raw_detail,
                fallback_fail_note=question.short_note_fail,
            )
            sub_qr = QuestionResult(
                id=str(s.get("id", "")).strip(),
                verdict=sub_verdict,
                confidence=sub_conf,
                logic_analysis=str(s.get("logic_analysis", "")).strip(),
                short_reason=sub_short,
                detail_reason=sub_detail,
                evidence_quote=str(s.get("evidence_quote", "")).strip()[:500],
                coords=parse_coords_0_to_1000(s.get("coords")),
                page_number=parse_page_number(s.get("page_number") or s.get("page")),
                source_file=str(s.get("source_file", "")).strip() or None,
                block_id=str(s.get("block_id", "")).strip() or None,
                token_usage=token_usage,
            )
            sub_question_results.append(sub_qr)

        normalized_questions.append(
            QuestionResult(
                id=question.id,
                verdict=aggregated_verdict,
                confidence=aggregated_confidence,
                logic_analysis=aggregated_logic,
                short_reason=short_reason,
                detail_reason=detail_reason,
                evidence_quote=evidence_quote,
                coords=coords,
                page_number=page_number,
                source_file=source_file,
                block_id=block_id,
                sub_results=tuple(sub_question_results) if sub_question_results else None,
                token_usage=token_usage,
            )
        )

    global_flags_raw = payload.get("global_flags", [])
    global_flags = [str(item).strip() for item in global_flags_raw if str(item).strip()]
    return {
        "questions": normalized_questions,
        "global_flags": merge_flags(global_flags),
    }


def normalize_feedback(
    *,
    verdict: str,
    raw_short_reason: str,
    raw_detail_reason: str,
    fallback_fail_note: str,
) -> tuple[str, str]:
    if verdict == "correct":
        return "", ""
    if verdict == "needs_review":
        first_line = re.split(r"[\r\n]+", str(raw_short_reason or ""), maxsplit=1)[0].strip()
        first_sentence = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)[0].strip()
        cleaned = " ".join(first_sentence.split())
        lowered = cleaned.lower()
        if lowered in {"n/a", "na", "none", "no reason provided by model.", ""}:
            cleaned = ""
        short_reason = clamp_short_reason(cleaned) if cleaned else (fallback_fail_note or "Needs review.")
        detail_reason = raw_detail_reason.strip() if raw_detail_reason else ""
        return short_reason, detail_reason

    short_reason = derive_short_reason(raw_short_reason=raw_short_reason, fallback_fail_note=fallback_fail_note)
    detail_reason = derive_detail_reason(
        raw_short_reason=raw_short_reason,
        raw_detail_reason=raw_detail_reason,
        short_reason=short_reason,
    )
    return short_reason, detail_reason


def derive_short_reason(*, raw_short_reason: str, fallback_fail_note: str) -> str:
    candidate = extract_pithy_sentence(
        raw_short_reason,
        max_chars=SHORT_REASON_MAX_CHARS,
        max_words=SHORT_REASON_MAX_WORDS,
    )
    if candidate and (not is_third_person_feedback(candidate)):
        return clamp_short_reason(candidate)

    return fallback_fail_note or ""


def derive_detail_reason(*, raw_short_reason: str, raw_detail_reason: str, short_reason: str) -> str:
    direct_detail = extract_detail_reason(raw_detail_reason)
    if direct_detail:
        return direct_detail

    overflow = extract_overflow_detail(raw_short_reason, short_reason)
    return extract_detail_reason(overflow)


def extract_detail_reason(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered in {"n/a", "na", "none", "no reason provided by model."}:
        return ""
    words = cleaned.split()
    if len(words) > DETAIL_REASON_MAX_WORDS:
        cleaned = " ".join(words[:DETAIL_REASON_MAX_WORDS]).rstrip()
    if len(cleaned) > DETAIL_REASON_MAX_CHARS:
        cleaned = cleaned[:DETAIL_REASON_MAX_CHARS].rstrip()
        if " " in cleaned:
            cleaned = cleaned.rsplit(" ", 1)[0].rstrip()
    return cleaned


def extract_overflow_detail(raw_short_reason: str, short_reason: str) -> str:
    cleaned = " ".join(str(raw_short_reason or "").split())
    if not cleaned:
        return ""
    if not short_reason:
        return cleaned
    if cleaned == short_reason:
        return ""
    if cleaned.startswith(short_reason):
        return cleaned[len(short_reason) :].lstrip(" .;:-")
    idx = cleaned.find(short_reason)
    if idx >= 0:
        return cleaned[idx + len(short_reason) :].lstrip(" .;:-")
    return ""


def clamp_short_reason(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= SHORT_REASON_MAX_CHARS:
        return cleaned
    clipped = cleaned[:SHORT_REASON_MAX_CHARS].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    return clipped or cleaned[:SHORT_REASON_MAX_CHARS].rstrip()


def extract_pithy_sentence(text: str, max_chars: int = 90, max_words: int = 16) -> str:
    first_line = re.split(r"[\r\n]+", str(text or ""), maxsplit=1)[0].strip()
    if not first_line:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)[0].strip()
    cleaned = " ".join(first_sentence.split())
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    if lowered in {"n/a", "na", "none", "no reason provided by model."}:
        return ""
    if len(cleaned) > max_chars or len(cleaned.split()) > max_words:
        return ""
    return cleaned


def is_third_person_feedback(text: str) -> bool:
    lowered = f" {text.lower()} "
    disallowed_tokens = (
        " the student ",
        " student ",
        " they ",
        " their ",
        " this answer ",
        " the response ",
    )
    return any(token in lowered for token in disallowed_tokens)


def normalize_locator_response(
    payload: JsonDict,
    rubric: RubricConfig,
    default_source_file: str,
) -> list[JsonDict]:
    allowed_ids = {question.id for question in rubric.questions}
    raw_items = payload.get("results")
    if not isinstance(raw_items, list):
        raw_items = payload.get("questions", [])
    if not isinstance(raw_items, list):
        return []

    normalized: list[JsonDict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        qid = normalize_question_id(item.get("q") or item.get("id"))
        if not qid or qid not in allowed_ids:
            continue
        coords = parse_coords_0_to_1000(item.get("coords"))
        if coords is None:
            continue
        confidence = normalize_confidence(item.get("confidence", 0.0))
        page_number = parse_page_number(item.get("page_number") or item.get("page"))
        source_file = str(item.get("source_file", "")).strip() or default_source_file
        normalized.append(
            {
                "id": qid,
                "coords": coords,
                "confidence": confidence,
                "page_number": page_number,
                "source_file": source_file,
            }
        )
    return normalized


def normalize_draft_rubric_payload(payload: JsonDict, assignment_id: str) -> JsonDict:
    """Normalize a DraftRubricConfig payload into a RubricConfig-compatible dict.

    This function is intentionally tolerant of partial / messy model output and
    fills in reasonable defaults so that the result can be serialized to YAML
    and loaded via load_rubric.
    """
    if not isinstance(payload, dict):
        raise ValueError("Draft rubric payload must be an object.")

    # --- Root fields ---------------------------------------------------------
    raw_assignment_id = str(payload.get("assignment_id") or "").strip()
    normalized_assignment_id = raw_assignment_id or str(assignment_id).strip() or "assignment"

    # Bands: ensure both check_plus_min and check_min are present and floats.
    default_bands = {"check_plus_min": 0.90, "check_min": 0.70}
    bands_raw = payload.get("bands")
    bands: dict[str, float] = {}
    if isinstance(bands_raw, dict):
        for key in ("check_plus_min", "check_min"):
            try:
                value = float(bands_raw.get(key))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                value = default_bands[key]
            bands[key] = value
    else:
        bands = dict(default_bands)

    scoring_mode_raw = str(payload.get("scoring_mode") or "").strip()
    scoring_mode = scoring_mode_raw or "equal_weights"

    try:
        partial_credit_value = float(payload.get("partial_credit"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        partial_credit_value = 0.5

    # --- Question list -------------------------------------------------------
    questions_raw = payload.get("questions") or []
    if not isinstance(questions_raw, list):
        questions_raw = []

    # First pass: collect numeric points where available.
    points_by_index: dict[int, float] = {}
    for idx, item in enumerate(questions_raw):
        if not isinstance(item, dict):
            continue
        try:
            points_val = float(item.get("points"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if points_val > 0:
            points_by_index[idx] = points_val

    total_points = sum(points_by_index.values())

    def _canonicalize_rubric_question_id(value: Any) -> str:
        """Best-effort normalization of question identifiers like 'Q1', '1)', '(a)' to '1' or 'a'."""
        cleaned = str(value or "").strip().lower()
        if not cleaned:
            return ""
        # Prefer bare numbers or letter+digits tokens.
        match = re.search(r"[a-z]+\d*|\d+", cleaned)
        return match.group(0) if match else cleaned

    # Build normalized question entries and track unique IDs.
    normalized_questions: list[JsonDict] = []
    seen_ids: set[str] = set()

    for idx, item in enumerate(questions_raw):
        if not isinstance(item, dict):
            continue

        raw_id = item.get("id") or item.get("label")
        qid = _canonicalize_rubric_question_id(raw_id)
        if not qid:
            # Fallback to sequential ids if model left id empty.
            qid = str(len(normalized_questions) + 1)
        # Deduplicate by keeping the first occurrence of each id.
        if qid in seen_ids:
            continue
        seen_ids.add(qid)

        # Label patterns and anchors.
        raw_patterns = item.get("label_patterns")
        label_patterns: list[str]
        if isinstance(raw_patterns, list) and raw_patterns:
            label_patterns = [str(v) for v in raw_patterns if str(v).strip()]
        else:
            label_patterns = [f"{qid})", f"{qid}.", f"({qid})"]

        scoring_rules_raw = str(item.get("scoring_rules") or "").strip()
        scoring_rules = scoring_rules_raw or "Define expected answer criteria."

        short_pass_raw = str(item.get("short_note_pass") or "").strip()
        short_note_pass = short_pass_raw or "Correct."

        short_fail_raw = str(item.get("short_note_fail") or "").strip()
        short_note_fail = short_fail_raw or "Needs revision."

        # Weight: prefer explicit weight, fall back to inferred points, then 1.0.
        weight_val: float | None
        try:
            weight_val = float(item.get("weight"))  # type: ignore[arg-type]
            if weight_val <= 0:
                weight_val = None
        except (TypeError, ValueError):
            weight_val = None

        if weight_val is None and total_points > 0 and idx in points_by_index:
            weight_val = float(points_by_index[idx]) / float(total_points)

        if weight_val is None:
            weight_val = 1.0

        raw_anchors = item.get("anchor_tokens")
        if isinstance(raw_anchors, list) and raw_anchors:
            anchor_tokens = [str(v) for v in raw_anchors if str(v).strip()]
        else:
            anchor_tokens = list(label_patterns)

        raw_expected_answers = item.get("expected_answers")
        if isinstance(raw_expected_answers, list) and raw_expected_answers:
            expected_answers = [str(v) for v in raw_expected_answers if str(v).strip()]
        else:
            expected_answers = []

        raw_scoring_criteria = item.get("scoring_criteria")
        scoring_criteria_list: list[dict[str, Any]] = []
        if isinstance(raw_scoring_criteria, list):
            for sc in raw_scoring_criteria:
                if isinstance(sc, dict):
                    req = str(sc.get("requirement") or "").strip()
                    if req:
                        try:
                            sc_w = float(sc.get("weight", 1.0))
                        except (TypeError, ValueError):
                            sc_w = 1.0
                        sc_p = str(sc.get("partial_if") or "").strip()
                        c_dict: dict[str, Any] = {"requirement": req, "weight": sc_w}
                        if sc_p:
                            c_dict["partial_if"] = sc_p
                        scoring_criteria_list.append(c_dict)

        raw_expected_numeric = item.get("expected_numeric")
        expected_numeric_dict: dict[str, Any] | None = None
        if isinstance(raw_expected_numeric, dict) and "value" in raw_expected_numeric:
            try:
                en_val = float(raw_expected_numeric["value"])
                en_tol = float(raw_expected_numeric.get("tolerance", 0.0))
                en_pct = bool(raw_expected_numeric.get("allow_percent", True))
                expected_numeric_dict = {
                    "value": en_val,
                    "tolerance": en_tol,
                    "allow_percent": en_pct,
                }
            except (TypeError, ValueError):
                expected_numeric_dict = None

        q_dict: dict[str, Any] = {
            "id": qid,
            "label_patterns": label_patterns,
            "scoring_rules": scoring_rules,
            "short_note_pass": short_note_pass,
            "short_note_fail": short_note_fail,
            "weight": weight_val,
            "anchor_tokens": anchor_tokens,
            "expected_answers": expected_answers,
        }
        if expected_numeric_dict is not None:
            q_dict["expected_numeric"] = expected_numeric_dict
        if scoring_criteria_list:
            q_dict["scoring_criteria"] = scoring_criteria_list

        normalized_questions.append(q_dict)

    # Renormalize weights so they sum to 1.0 (if possible) while preserving ratios.
    total_weight = sum(float(q.get("weight", 0.0)) for q in normalized_questions)
    if total_weight > 0:
        for q in normalized_questions:
            w = float(q.get("weight", 0.0))
            q["weight"] = w / total_weight

    # Sort questions by id for stability.
    normalized_questions.sort(key=lambda q: str(q.get("id")))

    return {
        "assignment_id": normalized_assignment_id,
        "bands": bands,
        "questions": normalized_questions,
        "scoring_mode": scoring_mode,
        "partial_credit": partial_credit_value,
    }


def normalize_verdict(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "pass": "correct",
        "correct": "correct",
        "partial": "partial",
        "partially_correct": "partial",
        "rounding_error": "rounding_error",
        "incorrect": "incorrect",
        "wrong": "incorrect",
        "needs_review": "needs_review",
        "uncertain": "needs_review",
        "unknown": "needs_review",
    }
    return aliases.get(normalized, "needs_review")


def normalize_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def normalize_question_id(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return ""
    return cleaned[0]


def parse_coords_0_to_1000(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)):
        return None

    if len(value) == 2:
        items = value
    elif len(value) == 4:
        try:
            ymin = float(value[0])
            xmin = float(value[1])
            ymax = float(value[2])
            xmax = float(value[3])
        except (TypeError, ValueError):
            return None
        items = [(ymin + ymax) / 2.0, (xmin + xmax) / 2.0]
    else:
        return None

    try:
        y = float(items[0])
        x = float(items[1])
    except (TypeError, ValueError):
        return None
    return (max(0.0, min(1000.0, y)), max(0.0, min(1000.0, x)))


def parse_page_number(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if number < 1:
        return None
    return number


def merge_flags(*groups: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            value = str(item).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            merged.append(value)
    return merged
