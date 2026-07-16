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
from grader.orchestrator import apply_locator_candidates
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


def test_find_anchor_in_doc_prefers_earliest_page_and_lowest_on_page():
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

    # Should choose the earliest page (index 0) and the lowest match on that page (y0 = 50).
    assert page_idx == 0
    assert point.y > 50


def test_find_anchor_in_doc_prefers_page_with_higher_priority_match():
    # Page 0: matches generic fallback "a)" (Priority 1)
    page0 = DummyPage(
        width=600,
        height=800,
        rects_by_token={
            "a)": [
                DummyRect(10, 100, 40, 120),
            ]
        },
    )
    # Page 1: matches explicit token "Question A" (Priority 3)
    page1 = DummyPage(
        width=600,
        height=800,
        rects_by_token={
            "Question A": [
                DummyRect(10, 200, 40, 220),
            ]
        },
    )
    doc = DummyDoc([page0, page1])

    page_idx, point = find_anchor_in_doc(
        doc=doc,
        question_id="a",
        label_patterns=["a)"],
        explicit_tokens=["Question A"],
    )

    # Should choose page 1 because "Question A" has priority 3 (explicit) while "a)" has priority 1 (generic fallback)
    assert page_idx == 1
    assert point.y > 200


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


def test_add_movable_freetext_annotation_with_border():
    import fitz
    from grader.annotate import add_movable_freetext_annotation
    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(10, 10, 100, 50)
    # Should not raise ValueError: cannot set border_color if rich_text is False
    add_movable_freetext_annotation(
        page=page,
        rect=rect,
        text="Test",
        fontsize=12,
        color=(0, 0, 0),
        subject="test",
        border_color=(1, 0, 0),
    )
    annots = list(page.annots())
    assert len(annots) == 1
    assert annots[0].type[1] == "FreeText"


import tempfile
from grader.annotate import annotate_submission_pdfs
from grader.types import SubmissionUnit, RubricConfig, QuestionRubric

def _make_pdf(path: Path, anchor_text: str = "4)") -> None:
    import fitz
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 120), anchor_text, fontsize=12, fontname="helv")
        doc.save(path)
    finally:
        doc.close()

def _make_submission(
    submissions_root: Path,
    folder_name: str,
    pdf_name: str = "submission.pdf",
    anchor_text: str = "4)",
) -> SubmissionUnit:
    folder_path = submissions_root / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    pdf_path = folder_path / pdf_name
    _make_pdf(pdf_path, anchor_text)
    return SubmissionUnit(
        folder_path=folder_path,
        folder_relpath=Path(folder_name),
        folder_token="123",
        student_name="Student",
        pdf_paths=[pdf_path],
    )

def _make_rubric(question_id: str) -> RubricConfig:
    return RubricConfig(
        assignment_id="test",
        bands={"check_plus_min": 0.9, "check_min": 0.7},
        questions=[
            QuestionRubric(
                id=question_id,
                label_patterns=[f"{question_id})"],
                scoring_rules="",
                short_note_pass="ok",
                short_note_fail="check",
            )
        ]
    )


def test_subpart_annotation_renders_multiple_marks():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        submissions_root = root / "subs"
        submission = _make_submission(submissions_root=submissions_root, folder_name="123 - Student")
        rubric = _make_rubric("4")
        
        # Sub-parts with distinct coordinates
        sub_results = (
            QuestionResult(
                id="4.a", verdict="correct", confidence=0.9, short_reason="", evidence_quote="",
                coords=(100, 100), page_number=1, source_file="submission.pdf"
            ),
            QuestionResult(
                id="4.b", verdict="incorrect", confidence=0.9, short_reason="wrong", evidence_quote="",
                coords=(200, 100), page_number=1, source_file="submission.pdf"
            ),
        )
        
        qr = QuestionResult(
            id="4", verdict="partial", confidence=0.9, short_reason="", evidence_quote="",
            sub_results=sub_results
        )
        
        output_dir = root / "out"
        output_paths, _ = annotate_submission_pdfs(
            submission=submission,
            rubric=rubric,
            question_results=[qr],
            output_dir=output_dir,
            submissions_root=submissions_root,
            final_band="check_min",
        )
        
        import fitz
        doc = fitz.open(output_paths[0])
        page = doc[0]
        annots = list(page.annots())
        
        # Expect header + fallback summary title + 2 marks for the subparts
        # Actually, because all subparts rendered, parent "4" is marked as rendered,
        # so there should be NO fallback summary title. 
        # Just Header + 4.a mark + 4.b mark = 3 annotations
        assert len(annots) == 3
        
        subjects = [annot.info.get("subject") for annot in annots]
        assert any("q=4.a" in s for s in subjects if s)
        assert any("q=4.b" in s for s in subjects if s)
        doc.close()


def test_subpart_annotation_falls_back_to_parent_anchor():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        submissions_root = root / "subs"
        submission = _make_submission(submissions_root=submissions_root, folder_name="123 - Student", anchor_text="4)")
        rubric = _make_rubric("4")
        
        # Sub-parts where one is missing coordinates completely
        sub_results = (
            QuestionResult(
                id="Q4.a", verdict="correct", confidence=0.9, short_reason="", evidence_quote="",
                coords=(100, 100), page_number=1, source_file="submission.pdf"
            ),
            QuestionResult(
                id="Q4.b", verdict="incorrect", confidence=0.9, short_reason="wrong", evidence_quote="",
                coords=None, page_number=None, source_file=None
            ),
        )
        
        qr = QuestionResult(
            id="4", verdict="partial", confidence=0.9, short_reason="", evidence_quote="",
            sub_results=sub_results
        )
        
        output_dir = root / "out"
        output_paths, _ = annotate_submission_pdfs(
            submission=submission,
            rubric=rubric,
            question_results=[qr],
            output_dir=output_dir,
            submissions_root=submissions_root,
            final_band="check_min",
        )
        
        import fitz
        doc = fitz.open(output_paths[0])
        page = doc[0]
        annots = list(page.annots())
        
        # Because fallback successfully placed 4.b at the parent anchor, 
        # both subparts rendered successfully. No summary fallback!
        # Header + 4.a mark + 4.b mark (at parent anchor) = 3
        assert len(annots) == 3
        
        subjects = [annot.info.get("subject") for annot in annots]
        assert any("q=4.a" in s for s in subjects if s)
        assert any("q=4.b" in s for s in subjects if s)
        
        # Check that 4.b's placement y is lower (greater) than the anchor 4) default position
        # but it should be rendered!
        doc.close()


def test_no_subresults_renders_single_mark():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        submissions_root = root / "subs"
        submission = _make_submission(submissions_root=submissions_root, folder_name="123 - Student", anchor_text="4)")
        rubric = _make_rubric("4")
        
        qr = QuestionResult(
            id="4", verdict="incorrect", confidence=0.9, short_reason="bad", evidence_quote="",
        )
        
        output_dir = root / "out"
        output_paths, _ = annotate_submission_pdfs(
            submission=submission,
            rubric=rubric,
            question_results=[qr],
            output_dir=output_dir,
            submissions_root=submissions_root,
            final_band="check_min",
        )
        
        import fitz
        doc = fitz.open(output_paths[0])
        page = doc[0]
        annots = list(page.annots())
        
        # Header + parent mark = 2 annotations
        assert len(annots) == 2
        
        subjects = [annot.info.get("subject") for annot in annots]
        assert any("q=4|" in s for s in subjects if s)
        doc.close()

