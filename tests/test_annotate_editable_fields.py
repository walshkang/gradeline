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


def make_submission(
    submissions_root: Path,
    folder_name: str,
    pdf_name: str = "submission.pdf",
    anchor_text: str = "a)",
) -> SubmissionUnit:
    folder_path = submissions_root / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    pdf_path = folder_path / pdf_name
    make_pdf(path=pdf_path, anchor_text=anchor_text)
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
    def test_marks_and_header_are_movable_freetext_annotations(self) -> None:
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
                    logic_analysis="", evidence_quote="...",
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
                page = annotated[0]
                annots = list(page.annots() or [])
                self.assertGreaterEqual(len(annots), 2)
                contents = [annot.info.get("content", "") for annot in annots]
                self.assertIn("Grade: CHECK_PLUS", contents)
                self.assertIn("✓ Qa", contents)
                mark_annot = next(
                    annot
                    for annot in annots
                    if (annot.info.get("subject", "")).startswith("question_mark|q=a|")
                )
                self.assertEqual(mark_annot.type[1], "FreeText")
                self.assertEqual(mark_annot.info.get("title", ""), "gradeline")
                self.assertNotEqual(mark_annot.flags & fitz.PDF_ANNOT_IS_PRINT, 0)

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
                    logic_analysis="", evidence_quote="...",
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
                page = annotated[0]
                annots = list(page.annots() or [])
                contents = [annot.info.get("content", "") for annot in annots]
                subjects = [annot.info.get("subject", "") for annot in annots]
                self.assertIn("Review Notes:", contents)
                self.assertTrue(any(value and value.startswith("x Qz:") for value in contents))
                self.assertTrue(any(subject.startswith("review_title|p=1") for subject in subjects))
                self.assertTrue(any(subject.startswith("review_note|q=z|p=1|n=1") for subject in subjects))

    def test_header_text_does_not_create_false_qe_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_root = root / "subs"
            submission = make_submission(
                submissions_root=submissions_root,
                folder_name="789 - Student",
                anchor_text="a)\nb)\nc)\nd)",
            )
            rubric = RubricConfig(
                assignment_id="test",
                bands={"check_plus_min": 0.9, "check_min": 0.7},
                questions=[
                    QuestionRubric(id=qid, label_patterns=[f"{qid})"], scoring_rules="", short_note_pass="ok", short_note_fail="check")
                    for qid in ["a", "b", "c", "d", "e"]
                ],
            )
            question_results = [
                QuestionResult(
                    id=qid,
                    verdict="incorrect",
                    confidence=0.6,
                    logic_analysis="",
                    short_reason=f"reason {qid}",
                    evidence_quote="",
                )
                for qid in ["a", "b", "c", "d", "e"]
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
                page = annotated[0]
                annots = list(page.annots() or [])
                qe_mark_annots = [
                    annot
                    for annot in annots
                    if (annot.info.get("subject", "")).startswith("question_mark|q=e|")
                ]
                self.assertEqual(qe_mark_annots, [])
                contents = [annot.info.get("content", "") for annot in annots]
                self.assertTrue(any(value and value.startswith("x Qe:") for value in contents))


    def test_annotation_uses_only_short_reason_not_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_root = root / "subs"
            submission = make_submission(submissions_root=submissions_root, folder_name="800 - Student")
            rubric = make_rubric("a")
            short = "Check your formula"
            detail = "You need to apply Bayes theorem correctly and show intermediate probability calculations step by step."
            question_results = [
                QuestionResult(
                    id="a",
                    verdict="incorrect",
                    confidence=0.8,
                    short_reason=short,
                    detail_reason=detail,
                    logic_analysis="", evidence_quote="...",
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
                page = annotated[0]
                annots = list(page.annots() or [])
                all_content = " ".join(annot.info.get("content", "") for annot in annots)
                self.assertIn(short, all_content)
                self.assertNotIn(detail, all_content)

    def test_annotation_short_reason_within_42_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_root = root / "subs"
            submission = make_submission(submissions_root=submissions_root, folder_name="801 - Student")
            rubric = make_rubric("a")
            short = "A very short note"
            question_results = [
                QuestionResult(
                    id="a",
                    verdict="incorrect",
                    confidence=0.8,
                    short_reason=short,
                    logic_analysis="", evidence_quote="...",
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
                page = annotated[0]
                annots = list(page.annots() or [])
                mark_annot = next(
                    annot
                    for annot in annots
                    if (annot.info.get("subject", "")).startswith("question_mark|q=a|")
                )
                content = mark_annot.info.get("content", "")
                self.assertIn(short, content)

    def test_annotation_long_short_reason_clipped_without_ellipsis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_root = root / "subs"
            submission = make_submission(submissions_root=submissions_root, folder_name="802 - Student")
            rubric = make_rubric("a")
            long_reason = "This is a significantly longer reason that will exceed the forty two character limit"
            question_results = [
                QuestionResult(
                    id="a",
                    verdict="incorrect",
                    confidence=0.8,
                    short_reason=long_reason,
                    logic_analysis="", evidence_quote="...",
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
                page = annotated[0]
                annots = list(page.annots() or [])
                mark_annot = next(
                    annot
                    for annot in annots
                    if (annot.info.get("subject", "")).startswith("question_mark|q=a|")
                )
                content = mark_annot.info.get("content", "")
                # Extract the reason part after "x Qa: "
                prefix = "x Qa: "
                self.assertTrue(content.startswith(prefix), f"Expected prefix '{prefix}', got: {content}")
                reason_part = content[len(prefix):]
                self.assertLessEqual(len(reason_part), 42)
                self.assertFalse(reason_part.endswith("..."))


if __name__ == "__main__":
    unittest.main()
