from __future__ import annotations

import fitz
import pytest

from grader.location_resolver import (
    find_anchor_in_doc,
    proportional_page_fallback,
)


def test_proportional_page_fallback_unrotated():
    doc = fitz.open()
    page = doc.new_page(width=200.0, height=400.0)

    # For total_questions = 1, y_ratio is 0.5 (middle)
    pt1 = proportional_page_fallback(page, question_index=0, total_questions=1)
    assert pt1.x == 24.0
    assert pt1.y == 200.0

    # For 3 questions, question_index 0, 1, 2 should space evenly down the page
    pt_q0 = proportional_page_fallback(page, question_index=0, total_questions=3)
    pt_q1 = proportional_page_fallback(page, question_index=1, total_questions=3)
    pt_q2 = proportional_page_fallback(page, question_index=2, total_questions=3)

    assert pt_q0.x == 24.0
    assert pt_q1.x == 24.0
    assert pt_q2.x == 24.0

    assert pt_q0.y < pt_q1.y < pt_q2.y
    assert pytest.approx(pt_q1.y, 0.1) == 200.0  # Middle question at 50%

    doc.close()


def test_proportional_page_fallback_rotated_90():
    doc = fitz.open()
    page = doc.new_page(width=200.0, height=400.0)
    page.set_rotation(90)

    pt = proportional_page_fallback(page, question_index=0, total_questions=1)
    assert pt is not None
    doc.close()


def test_find_anchor_in_doc_scanned_fallback_uses_left_margin():
    doc = fitz.open()
    # Empty scanned-like page (0 text, total_text_len = 0)
    page = doc.new_page(width=500.0, height=800.0)

    anchor = find_anchor_in_doc(
        doc=doc,
        question_id="1",
        label_patterns=[],
        explicit_tokens=[],
        fallback_y_ratio=0.5,
        question_index=0,
        total_questions=2,
    )
    assert anchor is not None
    page_idx, point = anchor
    assert page_idx == 0
    # Left margin alignment x == 24.0
    assert point.x == 24.0
    doc.close()
