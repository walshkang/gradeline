from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from grader.annotate import annotate_submission_pdfs
from grader.types import QuestionResult, QuestionRubric, RubricConfig, SubmissionUnit


def make_pdf(path: Path, anchor_text: str = "a)") -> None:
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 120), anchor_text, fontsize=12, fontname="helv")
        doc.save(path)
    finally:
        doc.close()


def make_submission(submissions_root: Path, folder_name: str, pdf_name: str = "submission.pdf") -> SubmissionUnit:
    folder_path = submissions_root / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    pdf_path = folder_path / pdf_name
    make_pdf(path=pdf_path)
    return SubmissionUnit(
        folder_path=folder_path,
        folder_relpath=Path(folder_name),
        folder_token=folder_name.split(" - ")[0],
        student_name=folder_name,
        pdf_paths=[pdf_path],
    )


def make_rubric(question_id: str = "a", label_patterns: list[str] | None = None) -> RubricConfig:
    return RubricConfig(
        assignment_id="test",
        bands={"check_plus_min": 0.9, "check_min": 0.7},
        questions=[
            QuestionRubric(
                id=question_id,
                label_patterns=label_patterns or [f"{question_id})"],
                scoring_rules="",
                short_note_pass="ok",
                short_note_fail="needs work",
            )
        ],
    )


class EditableAnnotationTests(unittest.TestCase):
    def test_marks_and_header_are_editable_widgets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_root = root / "subs"
            submission = make_submission(submissions_root=submissions_root, folder_name="123 - Student")
            rubric = make_rubric("a")
            question_results = [
                QuestionResult(
                    id="a",
                    verdict="correct",
                    confidence=0.95,
                    short_reason="Matches solution",
                    evidence_quote="...",
                )
            ]
            output_dir = root / "out"

            output_paths, _ = annotate_submission_pdfs(
                submission=submission,
                rubric=rubric,
                question_results=question_results,
                output_dir=output_dir,
                submissions_root=submissions_root,
                final_band="CHECK_PLUS",
                dry_run=False,
                annotate_dry_run_marks=False,
            )

            self.assertEqual(len(output_paths), 1)
            with fitz.open(output_paths[0]) as annotated:
                widgets = list(annotated[0].widgets() or [])
                self.assertGreaterEqual(len(widgets), 2)
                values = [widget.field_value for widget in widgets]
                self.assertIn("Grade: CHECK_PLUS", values)
                self.assertTrue(any(value and value.startswith("✓ Qa:") for value in values))
                mark_widget = next(
                    widget for widget in widgets if widget.field_name.startswith("sda_grader_question_mark_a_")
                )
                self.assertEqual(mark_widget.field_type, fitz.PDF_WIDGET_TYPE_TEXT)
                self.assertEqual(mark_widget.field_flags & fitz.PDF_FIELD_IS_READ_ONLY, 0)

    def test_unresolved_questions_use_editable_review_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_root = root / "subs"
            submission = make_submission(submissions_root=submissions_root, folder_name="456 - Student")
            rubric = make_rubric(question_id="z", label_patterns=["question-z-never-found"])
            question_results = [
                QuestionResult(
                    id="z",
                    verdict="incorrect",
                    confidence=0.6,
                    short_reason="No matching work found",
                    evidence_quote="...",
                )
            ]
            output_dir = root / "out"

            output_paths, _ = annotate_submission_pdfs(
                submission=submission,
                rubric=rubric,
                question_results=question_results,
                output_dir=output_dir,
                submissions_root=submissions_root,
                final_band="CHECK_MINUS",
                dry_run=False,
                annotate_dry_run_marks=False,
            )

            with fitz.open(output_paths[0]) as annotated:
                widgets = list(annotated[0].widgets() or [])
                values = [widget.field_value for widget in widgets]
                self.assertIn("Review Notes:", values)
                self.assertTrue(any(value and value.startswith("x Qz:") for value in values))


if __name__ == "__main__":
    unittest.main()
