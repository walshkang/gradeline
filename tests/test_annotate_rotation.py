import fitz
import pytest
from grader.annotate import (
    resolve_model_location,
    offset_mark_point,
    point_to_normalized,
    find_anchor_in_doc,
)
from grader.types import QuestionResult

def test_resolve_model_location_rotated_90():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.set_rotation(90)
    
    # page.rect after rotation: width=800, height=600.
    # Coords: y_norm = 500 (visual height midpoint = 300), x_norm = 500 (visual width midpoint = 400)
    # The visual point is Point(400, 300).
    # Unrotated point: Point(400, 300) * ~rotation_matrix => Point(300, 400).
    result = QuestionResult(
        id="q1",
        verdict="correct",
        confidence=1.0,
        short_reason="",
        evidence_quote="",
        coords=(500.0, 500.0),
        page_number=1,
    )
    
    resolved = resolve_model_location(doc, "test.pdf", result)
    assert resolved is not None
    page_idx, point, coords = resolved
    
    assert page_idx == 0
    assert abs(point.x - 300.0) < 1.0
    assert abs(point.y - 400.0) < 1.0
    assert coords == (500.0, 500.0)
    
    doc.close()


def test_point_to_normalized_rotated_90():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.set_rotation(90)
    
    # Unrotated point Point(300, 400) is the center of the 600x800 page.
    # In 90 degree rotated space, this point is visually at Point(400, 300)
    # which is (500, 500) normalized on the 800x600 visible page.
    p = fitz.Point(300, 400)
    coords = point_to_normalized(page, p)
    assert abs(coords[0] - 500.0) < 1.0
    assert abs(coords[1] - 500.0) < 1.0
    
    doc.close()


def test_offset_mark_point_rotated_90():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.set_rotation(90)
    
    # Unrotated point Point(300, 400).
    # In rotated space (800x600), visual point is (400, 300).
    # Applying layout offsets:
    # offset_x = 800 * 0.05 = 40
    # offset_y = -600 * 0.02 = -12
    # Visual offset point: (440, 288).
    # Unrotated visual offset point: Point(440, 288) * ~rotation_matrix => Point(288, 360).
    p = fitz.Point(300, 400)
    offset_p = offset_mark_point(page, p)
    assert abs(offset_p.x - 288.0) < 1.0
    assert abs(offset_p.y - 360.0) < 1.0
    
    doc.close()


def test_find_anchor_in_doc_fallback_unrotated():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    
    # Empty page, so search_for returns no matches.
    # Should fall back to the right margin of page 0.
    fallback_y_ratio = 0.25
    anchor = find_anchor_in_doc(
        doc=doc,
        question_id="q1",
        label_patterns=[],
        explicit_tokens=["q1"],
        fallback_y_ratio=fallback_y_ratio,
    )
    
    assert anchor is not None
    page_idx, point = anchor
    assert page_idx == 0
    # Right margin: 600 - 150 = 450
    # y: 800 * 0.25 = 200
    assert abs(point.x - 450.0) < 1.0
    assert abs(point.y - 200.0) < 1.0
    
    doc.close()


def test_find_anchor_in_doc_fallback_rotated_90():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.set_rotation(90)
    
    # Empty rotated page.
    # Visual dimensions: width=800, height=600.
    # Right margin in visual space: 800 - 150 = 650.
    # Visual y: 600 * 0.25 = 150.
    # Visual point: Point(650, 150).
    # Unrotated point: Point(650, 150) * ~rotation_matrix => Point(150, 150).
    fallback_y_ratio = 0.25
    anchor = find_anchor_in_doc(
        doc=doc,
        question_id="q1",
        label_patterns=[],
        explicit_tokens=["q1"],
        fallback_y_ratio=fallback_y_ratio,
    )
    
    assert anchor is not None
    page_idx, point = anchor
    assert page_idx == 0
    assert abs(point.x - 150.0) < 1.0
    assert abs(point.y - 150.0) < 1.0
    
    doc.close()
