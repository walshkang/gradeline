from __future__ import annotations

import fitz
import pytest

from grader.location_resolver import (
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
    resolve_model_location,
    should_render_question_marks,
    strip_regex_markers,
)
from grader.types import QuestionResult, TextBlock


def test_clean_subpart_label():
    assert clean_subpart_label("1", "1.a") == "a"
    assert clean_subpart_label("1", "Question 1a") == "a"
    assert clean_subpart_label("1", "q1b") == "b"
    assert clean_subpart_label("1", "a") == "a"
    assert clean_subpart_label("2", "2_c") == "c"
    assert clean_subpart_label("4", "Q4.a") == "a"
    assert clean_subpart_label("1a", "1a") == "1a"


def test_clamp():
    assert clamp(5.0, 0.0, 10.0) == 5.0
    assert clamp(-5.0, 0.0, 10.0) == 0.0
    assert clamp(15.0, 0.0, 10.0) == 10.0


def test_should_render_question_marks():
    assert should_render_question_marks(dry_run=False, annotate_dry_run_marks=False) is True
    assert should_render_question_marks(dry_run=True, annotate_dry_run_marks=False) is False
    assert should_render_question_marks(dry_run=True, annotate_dry_run_marks=True) is True


def test_is_literal_pattern_and_strip_regex():
    assert is_literal_pattern(r"Question 1:") is True
    assert is_literal_pattern(r"\bQuestion\b") is False
    assert strip_regex_markers(r"\bQuestion 1\b") == "Question 1"


def test_build_anchor_tokens():
    tokens = build_anchor_tokens("1", ["Question 1"], ["Q1"])
    assert "Q1" in tokens
    assert "1)" in tokens
    assert "1." in tokens
    assert "Question 1" in tokens
    # Ensure deduplicated
    assert len(tokens) == len(set(t.lower() for t in tokens))


def test_compact_reason():
    short = "Incorrect constant factor"
    assert compact_reason(short) == "Incorrect constant factor"

    long_text = "The calculated integral value was missing a crucial factor of pi in the final step of simplification"
    compacted = compact_reason(long_text, max_chars=40)
    assert len(compacted) <= 41
    assert compacted.endswith("…")


def test_mark_text_for_result():
    res_correct = QuestionResult(id="1", verdict="correct", confidence=1.0, short_reason="Good job", evidence_quote="")
    assert mark_text_for_result("1", res_correct) == "✓ Q1"

    res_rounding = QuestionResult(id="2", verdict="rounding_error", confidence=1.0, short_reason="Off by 0.01", evidence_quote="")
    assert mark_text_for_result("2", res_rounding) == "✓ Q2 ≈"

    res_fail = QuestionResult(id="3", verdict="incorrect", confidence=1.0, short_reason="Arithmetic mistake", evidence_quote="")
    assert mark_text_for_result("3", res_fail) == "x Q3: Arithmetic mistake"

    res_sub = QuestionResult(id="1a", verdict="incorrect", confidence=1.0, short_reason="Wrong sign", evidence_quote="")
    assert mark_text_for_result("1", res_sub, subpart_label="a") == "x Q1.a: Wrong sign"


def test_point_to_normalized():
    doc = fitz.open()
    page = doc.new_page(width=100, height=200)
    pt = fitz.Point(50, 100)
    y_norm, x_norm = point_to_normalized(page, pt)
    assert pytest.approx(y_norm, 0.1) == 500.0
    assert pytest.approx(x_norm, 0.1) == 500.0


def test_resolve_model_location_coords():
    doc = fitz.open()
    page = doc.new_page(width=100, height=200)
    res = QuestionResult(id="1", verdict="correct", confidence=1.0, short_reason="", evidence_quote="", coords=(500.0, 500.0), page_number=1)
    loc = resolve_model_location(doc, "test.pdf", res)
    assert loc is not None
    page_idx, point, norm = loc
    assert page_idx == 0
    assert pytest.approx(point.x, 0.1) == 50.0
    assert pytest.approx(point.y, 0.1) == 100.0


def test_resolve_model_location_block_id():
    doc = fitz.open()
    page = doc.new_page(width=100, height=200)
    block_reg = {"b1": TextBlock(id="b1", page=1, left=30.0, top=60.0, width=50.0, height=20.0, text="Problem 1", source="ocr")}
    res = QuestionResult(id="1", verdict="correct", confidence=1.0, short_reason="", evidence_quote="", block_id="b1")
    loc = resolve_model_location(doc, "test.pdf", res, block_registry=block_reg)
    assert loc is not None
    page_idx, point, norm, source = loc
    assert page_idx == 0
    assert point.x == 20.0  # max(15.0, 30.0 - 10.0)
    assert point.y == 60.0
    assert source == "block_id"


def test_find_answer_anchor_in_doc():
    doc = fitz.open()
    page = doc.new_page(width=500, height=800)
    page.insert_text(fitz.Point(50, 100), "1. Calculate mean: 11.534 ounces")

    q_res = QuestionResult(id="1", verdict="correct", confidence=1.0, short_reason="", evidence_quote="μ = 11.534")
    header_loc = (0, fitz.Point(50, 100))

    ans_loc = find_answer_anchor_in_doc(doc, "1", q_res, header_loc)
    assert ans_loc is not None
    page_idx, point, src = ans_loc
    assert page_idx == 0
    assert src == "answer_anchor"
    assert point.x > 50.0  # Placed adjacent to matched answer text

    # Fallback to right margin when answer text not found
    q_res_missing = QuestionResult(id="2", verdict="needs_review", confidence=0.0, short_reason="No work found", evidence_quote="")
    ans_loc_fallback = find_answer_anchor_in_doc(doc, "2", q_res_missing, header_loc)
    assert ans_loc_fallback is not None
    assert ans_loc_fallback[2] == "section_right_margin"
    assert ans_loc_fallback[1].x >= 400.0
