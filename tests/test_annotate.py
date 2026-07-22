from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from grader.annotate import (
    add_fallback_summary,
    find_anchor_in_doc,
    find_non_overlapping_rect,
    text_annotation_rect_from_baseline,
)
from grader.types import QuestionResult, QuestionRubric


def test_text_annotation_rect_multiline_wrap():
    doc = fitz.open()
    page = doc.new_page(width=612.0, height=792.0)
    
    # Large starting X position near right edge
    rect = text_annotation_rect_from_baseline(
        page=page,
        x=500.0,
        y=100.0,
        text="x Q1: This is a very long feedback comment that should be properly handled",
        fontsize=12.0,
        min_width=140.0,
    )
    
    # Must stay within right margin (width - 4.0 = 608.0)
    assert rect.x1 <= 608.0
    assert rect.x0 >= 4.0
    assert rect.y0 >= 4.0
    assert rect.y1 <= 788.0
    doc.close()


def test_find_non_overlapping_rect_page_clamping():
    doc = fitz.open()
    page = doc.new_page(width=612.0, height=792.0)
    
    candidate = fitz.Rect(550.0, 700.0, 700.0, 750.0)  # Intentionally out of bounds
    placed = [fitz.Rect(540.0, 690.0, 610.0, 740.0)]
    
    rect = find_non_overlapping_rect(page, candidate, placed)
    
    assert rect.x1 <= 608.0
    assert rect.y1 <= 788.0
    assert rect.x0 >= 4.0
    assert rect.y0 >= 4.0
    doc.close()


def test_fallback_summary_no_overlap():
    doc = fitz.open()
    page = doc.new_page(width=612.0, height=792.0)
    
    q1 = QuestionRubric(id="1", weight=1.0, label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail="Fail")
    q2 = QuestionRubric(id="2", weight=1.0, label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail="Fail")
    q3 = QuestionRubric(id="3", weight=1.0, label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail="Fail")
    
    result_map = {
        "1": QuestionResult(id="1", verdict="incorrect", confidence=1.0, short_reason="Wrong value", evidence_quote=""),
        "2": QuestionResult(id="2", verdict="incorrect", confidence=1.0, short_reason="Calculation error", evidence_quote=""),
        "3": QuestionResult(id="3", verdict="correct", confidence=1.0, short_reason="", evidence_quote=""),
    }
    
    add_fallback_summary(
        page,
        unresolved=[q1, q2, q3],
        result_map=result_map,
        title_fontsize=12.0,
        line_fontsize=12.0,
    )
    
    annots = list(page.annots() or [])
    rects = [a.rect for a in annots if a.info.get("subject", "").startswith("review_note|")]
    
    # Ensure zero vertical overlap between consecutive review notes
    for i in range(len(rects) - 1):
        assert rects[i+1].y0 >= rects[i].y1 - 1.0, f"Line {i+1} overlaps line {i}"
        
    doc.close()


def test_scanned_pdf_text_density_fallback():
    doc = fitz.open()
    page = doc.new_page(width=612.0, height=792.0)
    # Insert dummy image stream simulating a scanned page image
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 10, 10), False)
    page.insert_image((0, 0, 10, 10), pixmap=pix)
    # Insert tiny header text ("Homework 3") under 300 chars
    page.insert_text((50, 50), "Homework 3 - July 16")
    
    # Should resolve proportional anchor instead of returning None
    anchor = find_anchor_in_doc(
        doc=doc,
        question_id="3",
        label_patterns=[],
        explicit_tokens=["soda machine"],
        fallback_y_ratio=0.5,
    )
    
    assert anchor is not None
    page_idx, point = anchor
    assert page_idx == 0
    assert point.x > 0 and point.y > 0
    doc.close()


def test_block_registry_ocr_anchor_search():
    from grader.annotate import resolve_model_location
    from grader.types import TextBlock

    doc = fitz.open()
    page1 = doc.new_page(width=612.0, height=792.0)
    page2 = doc.new_page(width=612.0, height=792.0)

    block_registry = {
        "p1_b1": TextBlock(id="p1_b1", text="Problem 1", page=1, left=40.0, top=50.0, width=100.0, height=20.0, source="gemini_flash", confidence=1.0),
        "p1_b2": TextBlock(id="p1_b2", text="a) P(R > 30)", page=1, left=40.0, top=700.0, width=150.0, height=20.0, source="gemini_flash", confidence=1.0),
        "p2_b1": TextBlock(id="p2_b1", text="b) P(R < 0)", page=2, left=40.0, top=50.0, width=150.0, height=20.0, source="gemini_flash", confidence=1.0),
        "p2_b2": TextBlock(id="p2_b2", text="c) P(6 < R < 14)", page=2, left=40.0, top=200.0, width=150.0, height=20.0, source="gemini_flash", confidence=1.0),
    }

    # Search for 2a should find p1_b2 on Page 1 (index 0)
    anchor = find_anchor_in_doc(
        doc=doc,
        question_id="2a",
        label_patterns=["2a"],
        explicit_tokens=["a)"],
        fallback_y_ratio=0.5,
        block_registry=block_registry,
    )

    assert anchor is not None
    page_idx, point = anchor
    assert page_idx == 0
    assert point.y == 700.0
    assert point.x == 30.0  # max(15.0, 40.0 - 10.0)

    # resolve_model_location with block_id uses left margin x
    qres = QuestionResult(id="2a", verdict="correct", confidence=1.0, short_reason="", evidence_quote="", block_id="p1_b2")
    loc = resolve_model_location(doc, "test.pdf", qres, block_registry=block_registry)
    assert loc is not None
    assert loc[0] == 0
    assert loc[1].x == 30.0
    assert loc[1].y == 700.0

    doc.close()

