from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from grader.report import write_brightspace_import_csv
from grader.types import (
    GradeResult,
    QuestionResult,
    SubmissionResult,
    SubmissionUnit,
)


def make_submission_result(
    folder_name: str,
    folder_token: str,
    student_name: str,
    band: str,
    points: str,
) -> SubmissionResult:
    submission = SubmissionUnit(
        folder_path=Path(folder_name),
        folder_relpath=Path(folder_name),
        folder_token=folder_token,
        student_name=student_name,
        pdf_paths=[],
    )
    grade_result = GradeResult(
        percent=100.0,
        band=band,
        points=points,
        has_needs_review=False,
        per_question_scores={},
    )
    return SubmissionResult(
        submission=submission,
        question_results=[
            QuestionResult(id="a", verdict="correct", confidence=1.0, short_reason="ok", evidence_quote="")
        ],
        grade_result=grade_result,
        output_pdf_paths=[],
        extraction_sources={},
        global_flags=[],
    )


class ReportCsvTests(unittest.TestCase):
    def test_writes_template_and_matches_by_name_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.csv"
            output_dir = root / "out"
            output_dir.mkdir()

            with template.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "OrgDefinedId",
                        "First Name",
                        "Last Name",
                        "Assignment 1 Points Grade",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "OrgDefinedId": "unknown",
                        "First Name": "Jane",
                        "Last Name": "Doe",
                        "Assignment 1 Points Grade": "",
                    }
                )

            result = make_submission_result(
                folder_name="123-456 - Jane Doe - Feb 24",
                folder_token="123-456",
                student_name="Jane Doe",
                band="Check Plus",
                points="100",
            )
            out_csv, warnings = write_brightspace_import_csv(
                output_dir=output_dir,
                template_csv_path=template,
                submission_results=[result],
                grade_column="Assignment 1 Points Grade",
                identifier_column="OrgDefinedId",
                comment_column=None,
            )
            self.assertEqual(len(warnings), 0)

            with out_csv.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["Assignment 1 Points Grade"], "100")

    def test_resolves_grade_column_by_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.csv"
            output_dir = root / "out"
            output_dir.mkdir()

            header = "Assignment 1 Points Grade <Numeric MaxPoints:2>"
            with template.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "Username",
                        "Last Name",
                        "First Name",
                        header,
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Username": "unknown",
                        "First Name": "Jane",
                        "Last Name": "Doe",
                        header: "",
                    }
                )

            result = make_submission_result(
                folder_name="123-456 - Jane Doe - Feb 24",
                folder_token="123-456",
                student_name="Jane Doe",
                band="Check Plus",
                points="100",
            )
            out_csv, warnings = write_brightspace_import_csv(
                output_dir=output_dir,
                template_csv_path=template,
                submission_results=[result],
                grade_column="Assignment 1 Points Grade",
                identifier_column="Username",
                comment_column=None,
            )
            self.assertEqual(len(warnings), 0)

            with out_csv.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0][header], "100")

    def test_identifier_falls_back_to_username(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.csv"
            output_dir = root / "out"
            output_dir.mkdir()

            with template.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "Username",
                        "Last Name",
                        "First Name",
                        "Assignment 1 Points Grade",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Username": "123456",
                        "First Name": "Jane",
                        "Last Name": "Doe",
                        "Assignment 1 Points Grade": "",
                    }
                )

            result = make_submission_result(
                folder_name="123456 - Jane Doe - Feb 24",
                folder_token="123456",
                student_name="Jane Doe",
                band="Check Plus",
                points="100",
            )
            out_csv, warnings = write_brightspace_import_csv(
                output_dir=output_dir,
                template_csv_path=template,
                submission_results=[result],
                grade_column="Assignment 1 Points Grade",
                identifier_column="OrgDefinedId",
                comment_column=None,
            )

            self.assertTrue(any("using 'Username'" in warning for warning in warnings))
            with out_csv.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["Assignment 1 Points Grade"], "100")

    def test_supports_custom_output_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.csv"
            output_dir = root / "out"
            output_dir.mkdir()

            with template.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "OrgDefinedId",
                        "First Name",
                        "Last Name",
                        "Assignment 1 Points Grade",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "OrgDefinedId": "123",
                        "First Name": "Jane",
                        "Last Name": "Doe",
                        "Assignment 1 Points Grade": "",
                    }
                )

            result = make_submission_result(
                folder_name="123 - Jane Doe - Feb 24",
                folder_token="123",
                student_name="Jane Doe",
                band="Check Plus",
                points="100",
            )
            out_csv, warnings = write_brightspace_import_csv(
                output_dir=output_dir,
                template_csv_path=template,
                submission_results=[result],
                grade_column="Assignment 1 Points Grade",
                identifier_column="OrgDefinedId",
                comment_column=None,
                output_filename="custom.csv",
            )
            self.assertEqual(warnings, [])
            self.assertEqual(out_csv.name, "custom.csv")
            self.assertTrue(out_csv.exists())


if __name__ == "__main__":
    unittest.main()
