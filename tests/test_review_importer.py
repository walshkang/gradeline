from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import fitz

from grader.review.importer import ReviewInitError, initialize_review_state


HEADERS = [
    "folder",
    "student_name",
    "pdf_count",
    "pdfs",
    "percent",
    "band",
    "points",
    "question_id",
    "verdict",
    "confidence",
    "reason",
    "evidence_quote",
    "source_file",
    "page_number",
    "coords_y",
    "coords_x",
    "placement_source",
    "error",
]


def make_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 120), "a)", fontsize=12, fontname="helv")
        doc.save(path)
    finally:
        doc.close()


class ReviewImporterTests(unittest.TestCase):
    def test_init_creates_state_with_rubric_and_grade_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir = root / "subs"
            student_folder = submissions_dir / "123 - Jane Doe"
            student_folder.mkdir(parents=True)
            pdf_path = student_folder / "submission.pdf"
            make_pdf(pdf_path)

            output_dir = root / "out"
            output_dir.mkdir()

            rubric_yaml = root / "rubric.yaml"
            rubric_yaml.write_text(
                """
assignment_id: a1
bands:
  check_plus_min: 0.9
  check_min: 0.7
questions:
  - id: a
    label_patterns: ["a)"]
    scoring_rules: ""
    short_note_pass: "ok"
    short_note_fail: "check"
""".strip(),
                encoding="utf-8",
            )

            template_csv = root / "template.csv"
            template_csv.write_text("OrgDefinedId,Assignment 1 Points Grade\n123,\n", encoding="utf-8")

            diagnostics = {
                "run_id": "run123",
                "args_snapshot": {
                    "submissions_dir": str(submissions_dir),
                    "rubric_yaml": str(rubric_yaml),
                    "grades_template_csv": str(template_csv),
                    "grade_column": "Assignment 1 Points Grade",
                    "identifier_column": "OrgDefinedId",
                    "check_plus_points": "100",
                    "check_points": "85",
                    "check_minus_points": "65",
                    "review_required_points": "0",
                },
            }
            (output_dir / "grading_diagnostics.json").write_text(json.dumps(diagnostics), encoding="utf-8")

            with (output_dir / "grading_audit.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(HEADERS)
                writer.writerow(
                    [
                        "123 - Jane Doe",
                        "Jane Doe",
                        "1",
                        "submission.pdf",
                        "100.00",
                        "Check Plus",
                        "100",
                        "a",
                        "correct",
                        "0.95",
                        "Looks good",
                        "sample",
                        "submission.pdf",
                        "1",
                        "120",
                        "210",
                        "model_coords",
                        "",
                    ]
                )

            state_path = initialize_review_state(output_dir=output_dir, rubric_yaml=None)
            self.assertTrue(state_path.exists())

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["run_metadata"]["run_id"], "run123")
            self.assertEqual(payload["grading_context"]["grade_points"]["Check Plus"], "100")
            self.assertEqual(payload["grading_context"]["rubric"]["assignment_id"], "a1")

            submissions = payload["submissions"]
            self.assertEqual(len(submissions), 1)
            submission = next(iter(submissions.values()))
            self.assertEqual(submission["identity"]["student_name"], "Jane Doe")
            self.assertEqual(submission["questions"]["a"]["auto"]["coords"], [120.0, 210.0])
            self.assertEqual(submission["questions"]["a"]["final"]["coords"], [120.0, 210.0])

            events_path = output_dir / "review" / "review_events.jsonl"
            self.assertTrue(events_path.exists())
            self.assertIn("state_initialized", events_path.read_text(encoding="utf-8"))

    def test_init_requires_resolvable_rubric_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "grading_diagnostics.json").write_text(json.dumps({"args_snapshot": {}}), encoding="utf-8")
            (output_dir / "grading_audit.csv").write_text("folder\n", encoding="utf-8")

            with self.assertRaises(ReviewInitError):
                initialize_review_state(output_dir=output_dir, rubric_yaml=None)


if __name__ == "__main__":
    unittest.main()
