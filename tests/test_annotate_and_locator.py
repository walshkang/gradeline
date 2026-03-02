import types

from pathlib import Path

from grader.annotate import (
    ANCHOR_LEFT_MARGIN_RATIO,
    ANCHOR_TOP_MARGIN_RATIO,
    ANCHOR_BOTTOM_MARGIN_RATIO,
    DEFAULT_ANNOTATION_FONT_SIZE,
    find_anchor_in_doc,
    offset_mark_point,
)
from grader.cli import apply_locator_candidates
from grader.types import QuestionResult


class DummyRect:
    def __init__(self, x0, y0, x1, y1):
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1


class DummyPage:
    def __init__(self, width, height, rects_by_token):
        self.rect = types.SimpleNamespace(width=width, height=height)
        self._rects_by_token = rects_by_token

    def search_for(self, token):
        return list(self._rects_by_token.get(token, []))


class DummyDoc:
    def __init__(self, pages):
        self._pages = pages

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, idx):
        return self._pages[idx]


def test_find_anchor_in_doc_prefers_latest_page_and_lowest_on_page():
    token = "a)"
    # Page 0: one match near top-left.
    page0 = DummyPage(
        width=600,
        height=800,
        rects_by_token={
            token: [
                DummyRect(10, 50, 40, 70),
            ]
        },
    )
    # Page 1: two matches in left margin; one lower on page.
    page1 = DummyPage(
        width=600,
        height=800,
        rects_by_token={
            token: [
                DummyRect(10, 100, 40, 120),
                DummyRect(10, 400, 40, 420),
            ]
        },
    )
    doc = DummyDoc([page0, page1])

    page_idx, point = find_anchor_in_doc(
        doc=doc,
        question_id="a",
        label_patterns=[],
        explicit_tokens=[token],
    )

    # Should choose the latest page (index 1) and the lowest match on that page (y0 = 400).
    assert page_idx == 1
    assert point.y > 400


def test_offset_mark_point_uses_layout_aware_offsets():
    page = types.SimpleNamespace(rect=types.SimpleNamespace(width=1000.0, height=800.0))
    point = types.SimpleNamespace(x=100.0, y=200.0)

    new_point = offset_mark_point(page=page, point=point)

    # Expect a small rightward and upward move, scaled by page size.
    assert new_point.x > point.x
    assert new_point.y < point.y


def test_apply_locator_candidates_only_fills_missing_coords_and_sets_source():
    qr_with_coords = QuestionResult(
        id="a",
        verdict="correct",
        confidence=1.0,
        short_reason="",
        evidence_quote="",
        coords=(100.0, 200.0),
    )
    qr_missing = QuestionResult(
        id="b",
        verdict="correct",
        confidence=1.0,
        short_reason="",
        evidence_quote="",
    )
    candidates = {
        "a": [
            {
                "id": "a",
                "coords": (300.0, 400.0),
                "page_number": 2,
                "source_file": "foo.pdf",
                "confidence": 0.9,
            }
        ],
        "b": [
            {
                "id": "b",
                "coords": (500.0, 600.0),
                "page_number": 3,
                "source_file": "bar.pdf",
                "confidence": 0.95,
            }
        ],
    }
    pdf_paths = [Path("foo.pdf"), Path("bar.pdf")]

    updated = apply_locator_candidates(
        question_results=[qr_with_coords, qr_missing],
        candidates=candidates,
        pdf_paths=pdf_paths,
    )

    updated_map = {r.id: r for r in updated}

    # Existing coords should be preserved.
    assert updated_map["a"].coords == qr_with_coords.coords
    assert updated_map["a"].placement_source != "locator_coords"

    # Missing coords should be filled from locator and properly tagged.
    assert updated_map["b"].coords == (500.0, 600.0)
    assert updated_map["b"].placement_source == "locator_coords"

