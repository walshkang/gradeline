from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import fitz

from grader.review.exporter import export_review_outputs
from grader.review.state import state_path_for_output, write_state_atomic
from grader.review.types import SCHEMA_VERSION


def make_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 120), "a)", fontsize=12, fontname="helv")
        doc.save(path)
    finally:
        doc.close()


class ReviewExporterTests(unittest.TestCase):
    def test_export_writes_reviewed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir = root / "subs"
            student_dir = submissions_dir / "123 - Jane Doe"
            student_dir.mkdir(parents=True)
            pdf_path = student_dir / "submission.pdf"
            make_pdf(pdf_path)

            output_dir = root / "out"
            output_dir.mkdir()
            (output_dir / "review").mkdir()

            template_csv = root / "template.csv"
            template_csv.write_text(
                "OrgDefinedId,First Name,Last Name,Assignment 1 Points Grade\n123,Jane,Doe,\n",
                encoding="utf-8",
            )

            submission_id = "sub-1"
            state = {
                "schema_version": SCHEMA_VERSION,
                "run_metadata": {
                    "run_id": "run123",
                    "output_dir": str(output_dir),
                    "initialized_at": "2026-02-25T00:00:00Z",
                    "updated_at": "2026-02-25T00:00:00Z",
                },
                "grading_context": {
                    "args_snapshot": {
                        "submissions_dir": str(submissions_dir),
                        "grades_template_csv": str(template_csv),
                        "grade_column": "Assignment 1 Points Grade",
                        "identifier_column": "OrgDefinedId",
                    },
                    "grade_points": {
                        "Check Plus": "100",
                        "Check": "85",
                        "Check Minus": "65",
                        "REVIEW_REQUIRED": "0",
                    },
                    "rubric": {
                        "assignment_id": "a1",
                        "bands": {"check_plus_min": 0.9, "check_min": 0.7},
                        "scoring_mode": "equal_weights",
                        "partial_credit": 0.5,
                        "questions": [
                            {
                                "id": "a",
                                "label_patterns": ["a)"],
                                "scoring_rules": "",
                                "short_note_pass": "ok",
                                "short_note_fail": "check",
                                "weight": 1.0,
                                "anchor_tokens": [],
                            }
                        ],
                    },
                },
                "submissions": {
                    submission_id: {
                        "submission_id": submission_id,
                        "identity": {
                            "folder_path": str(student_dir),
                            "folder_relpath": "123 - Jane Doe",
                            "folder_token": "123",
                            "student_name": "Jane Doe",
                            "pdf_paths": [str(pdf_path)],
                        },
                        "auto_summary": {"percent": 0.0, "band": "Check Minus", "points": "65", "error": "", "flags": []},
                        "final_summary": {"percent": 100.0, "band": "Check Plus", "points": "100"},
                        "review_status": "done",
                        "note": "",
                        "updated_at": "2026-02-25T00:00:00Z",
                        "questions": {
                            "a": {
                                "id": "a",
                                "auto": {
                                    "verdict": "incorrect",
                                    "confidence": 0.2,
                                    "short_reason": "no",
                                    "evidence_quote": "",
                                    "coords": [100.0, 100.0],
                                    "page_number": 1,
                                    "source_file": "submission.pdf",
                                    "placement_source": "model_coords",
                                },
                                "final": {
                                    "verdict": "correct",
                                    "confidence": 0.95,
                                    "short_reason": "good",
                                    "evidence_quote": "",
                                    "coords": [100.0, 100.0],
                                    "page_number": 1,
                                    "source_file": "submission.pdf",
                                    "placement_source": "model_coords",
                                },
                                "is_overridden": True,
                                "updated_at": "2026-02-25T00:00:00Z",
                            }
                        },
                    }
                },
            }

            write_state_atomic(state_path_for_output(output_dir), state)
            artifacts = export_review_outputs(output_dir)

            self.assertIn("Grading audit reviewed CSV", artifacts)
            self.assertIn("Review queue reviewed CSV", artifacts)
            self.assertIn("Brightspace reviewed import CSV", artifacts)
            self.assertIn("Review decisions JSON", artifacts)

            review_dir = output_dir / "review"
            self.assertTrue((review_dir / "grading_audit_reviewed.csv").exists())
            self.assertTrue((review_dir / "review_queue_reviewed.csv").exists())
            self.assertTrue((review_dir / "brightspace_grades_import_reviewed.csv").exists())
            self.assertTrue((review_dir / "review_decisions.json").exists())

            reviewed_pdf = review_dir / "reviewed_pdfs" / "123 - Jane Doe" / "submission.pdf"
            self.assertTrue(reviewed_pdf.exists())

            decisions = json.loads((review_dir / "review_decisions.json").read_text(encoding="utf-8"))
            self.assertEqual(decisions["submissions"][submission_id]["questions"]["a"]["final"]["verdict"], "correct")


if __name__ == "__main__":
    unittest.main()
