from __future__ import annotations

from pathlib import Path
import fitz
import pytest

from grader.annotation_state import AnnotationSession
from grader.annotate import annotate_submission_pdfs
from grader.types import QuestionResult, QuestionRubric, RubricConfig, SubmissionUnit


def test_annotation_session_lifecycle():
    session = AnnotationSession()
    assert len(session.placed_rects) == 0
    assert len(session.rendered) == 0
    assert len(session.rendered_subparts) == 0

    session.mark_rendered("1")
    assert session.is_rendered("1")
    assert not session.is_rendered("2")

    session.mark_subpart_rendered("1.a")
    assert session.is_subpart_rendered("1.a")
    assert not session.is_subpart_rendered("1.b")

    session.record_placement("1", {"placement_source": "test", "page_number": 1})
    assert session.placement_details["1"]["placement_source"] == "test"

    results = [
        QuestionResult(
            id="1",
            verdict="correct",
            confidence=1.0,
            short_reason="Good",
            evidence_quote="Correct",
        ),
    ]
    updated = session.finalize_updated_results(results)
    assert updated[0].placement_source == "test"
    assert updated[0].page_number == 1


def test_pipeline_single_pdf_annotation(tmp_path: Path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "Question 1 Work and solution")
    input_pdf = tmp_path / "student.pdf"
    doc.save(input_pdf)
    doc.close()

    submission = SubmissionUnit(
        folder_path=tmp_path,
        folder_relpath=Path("student1"),
        folder_token="student1",
        student_name="Student 1",
        pdf_paths=[input_pdf],
    )
    rubric = RubricConfig(
        assignment_id="HW1",
        bands={"A": 90.0},
        questions=[
            QuestionRubric(
                id="1",
                label_patterns=["1"],
                scoring_rules="Standard",
                short_note_pass="Pass",
                short_note_fail="Fail",
                anchor_tokens=["Question 1"],
            ),
        ],
    )
    question_results = [
        QuestionResult(
            id="1",
            verdict="correct",
            confidence=1.0,
            short_reason="Correct",
            evidence_quote="1",
        ),
    ]

    output_dir = tmp_path / "output"
    out_paths, updated_results = annotate_submission_pdfs(
        submission=submission,
        rubric=rubric,
        question_results=question_results,
        output_dir=output_dir,
        submissions_root=tmp_path,
        final_band="A",
    )

    assert len(out_paths) == 1
    assert out_paths[0].exists()
    assert len(updated_results) == 1
    assert updated_results[0].placement_source is not None


def test_pipeline_subparts_annotation(tmp_path: Path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "Question 1 work")
    page.insert_text((50, 200), "a) Subpart A answer")
    page.insert_text((50, 300), "b) Subpart B answer")
    input_pdf = tmp_path / "student_sub.pdf"
    doc.save(input_pdf)
    doc.close()

    submission = SubmissionUnit(
        folder_path=tmp_path,
        folder_relpath=Path("student2"),
        folder_token="student2",
        student_name="Student 2",
        pdf_paths=[input_pdf],
    )
    rubric = RubricConfig(
        assignment_id="HW1",
        bands={"A": 90.0},
        questions=[
            QuestionRubric(
                id="1",
                label_patterns=["1"],
                scoring_rules="Standard",
                short_note_pass="Pass",
                short_note_fail="Fail",
                anchor_tokens=["Question 1"],
            ),
        ],
    )
    sub_results = (
        QuestionResult(
            id="1.a",
            verdict="correct",
            confidence=1.0,
            short_reason="Sub A ok",
            evidence_quote="a)",
        ),
        QuestionResult(
            id="1.b",
            verdict="incorrect",
            confidence=1.0,
            short_reason="Sub B wrong",
            evidence_quote="b)",
        ),
    )
    question_results = [
        QuestionResult(
            id="1",
            verdict="partial",
            confidence=1.0,
            short_reason="Partial credit",
            evidence_quote="1",
            sub_results=sub_results,
        ),
    ]

    output_dir = tmp_path / "output"
    out_paths, updated_results = annotate_submission_pdfs(
        submission=submission,
        rubric=rubric,
        question_results=question_results,
        output_dir=output_dir,
        submissions_root=tmp_path,
        final_band="B",
    )

    assert len(out_paths) == 1
    assert out_paths[0].exists()
    assert len(updated_results) == 1


def test_pipeline_summary_fallback(tmp_path: Path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "Blank document text")
    input_pdf = tmp_path / "student_blank.pdf"
    doc.save(input_pdf)
    doc.close()

    submission = SubmissionUnit(
        folder_path=tmp_path,
        folder_relpath=Path("student3"),
        folder_token="student3",
        student_name="Student 3",
        pdf_paths=[input_pdf],
    )
    rubric = RubricConfig(
        assignment_id="HW1",
        bands={"A": 90.0},
        questions=[
            QuestionRubric(
                id="99",
                label_patterns=["99"],
                scoring_rules="Standard",
                short_note_pass="Pass",
                short_note_fail="Fail",
                anchor_tokens=["Unfindable Token 99"],
            ),
        ],
    )
    question_results = [
        QuestionResult(
            id="99",
            verdict="incorrect",
            confidence=1.0,
            short_reason="Missing",
            evidence_quote="",
        ),
    ]

    output_dir = tmp_path / "output"
    out_paths, updated_results = annotate_submission_pdfs(
        submission=submission,
        rubric=rubric,
        question_results=question_results,
        output_dir=output_dir,
        submissions_root=tmp_path,
        final_band="F",
    )

    assert len(out_paths) == 1
    assert updated_results[0].placement_source == "summary_fallback"
