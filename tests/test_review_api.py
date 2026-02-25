from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grader.review.api import ReviewApi, ReviewApiError, coerce_coords_payload
from grader.review.state import state_path_for_output, write_state_atomic
from grader.review.types import SCHEMA_VERSION


def make_state(output_dir: Path) -> None:
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
                "submissions_dir": str(output_dir / "subs"),
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
                    "folder_path": str(output_dir / "subs" / "123 - Jane"),
                    "folder_relpath": "123 - Jane",
                    "folder_token": "123",
                    "student_name": "Jane",
                    "pdf_paths": [str(output_dir / "subs" / "123 - Jane" / "submission.pdf")],
                },
                "auto_summary": {"percent": 0.0, "band": "Check Minus", "points": "65", "error": "", "flags": []},
                "final_summary": {"percent": 0.0, "band": "Check Minus", "points": "65"},
                "review_status": "todo",
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
                            "coords": [100.0, 200.0],
                            "page_number": 1,
                            "source_file": "submission.pdf",
                            "placement_source": "model_coords",
                        },
                        "final": {
                            "verdict": "incorrect",
                            "confidence": 0.2,
                            "short_reason": "no",
                            "evidence_quote": "",
                            "coords": [100.0, 200.0],
                            "page_number": 1,
                            "source_file": "submission.pdf",
                            "placement_source": "model_coords",
                        },
                        "is_overridden": False,
                        "updated_at": "2026-02-25T00:00:00Z",
                    }
                },
            }
        },
    }

    (output_dir / "review").mkdir(parents=True, exist_ok=True)
    write_state_atomic(state_path_for_output(output_dir), state)


class ReviewApiTests(unittest.TestCase):
    def test_patch_question_recomputes_summary_and_sets_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            make_state(output_dir)
            api = ReviewApi(output_dir)

            response = api.patch_question(
                "sub-1",
                "a",
                {
                    "verdict_final": "correct",
                    "confidence_final": 0.95,
                    "coords_final": [333, 444],
                },
            )

            self.assertEqual(response["summary"]["band"], "Check Plus")
            self.assertEqual(response["summary"]["points"], "100")
            self.assertEqual(response["question"]["final"]["coords"], [333.0, 444.0])
            self.assertTrue(response["question"]["is_overridden"])

            persisted = json.loads((output_dir / "review" / "review_state.json").read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["submissions"]["sub-1"]["final_summary"]["band"],
                "Check Plus",
            )

    def test_patch_question_rejects_invalid_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            make_state(output_dir)
            api = ReviewApi(output_dir)

            with self.assertRaises(ReviewApiError):
                api.patch_question("sub-1", "a", {"source_file_final": "other.pdf"})

    def test_coords_payload_preserves_yx_order(self) -> None:
        coords = coerce_coords_payload([125, 875])
        self.assertEqual(coords, [125.0, 875.0])

    def test_patch_grading_context_recomputes_submission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            make_state(output_dir)
            api = ReviewApi(output_dir)

            response = api.patch_grading_context(
                {
                    "grade_points": {
                        "Check Plus": "110",
                        "Check": "90",
                        "Check Minus": "70",
                        "REVIEW_REQUIRED": "0",
                    },
                    "rubric": {
                        "assignment_id": "a1",
                        "bands": {"check_plus_min": 0.8, "check_min": 0.6},
                        "scoring_mode": "equal_weights",
                        "partial_credit": 0.5,
                        "questions": [
                            {
                                "id": "a",
                                "label_patterns": ["a)"],
                                "scoring_rules": "allow partial",
                                "short_note_pass": "ok",
                                "short_note_fail": "check",
                                "weight": 1.0,
                                "anchor_tokens": [],
                            }
                        ],
                    },
                }
            )

            self.assertEqual(response["recomputed_submissions"], 1)
            self.assertEqual(response["grading_context"]["grade_points"]["Check Plus"], "110")
            self.assertEqual(response["grading_context"]["rubric"]["bands"]["check_plus_min"], 0.8)

            run_payload = api.get_run()
            self.assertIn("args_snapshot", run_payload["grading_context"])

    def test_get_submission_supports_document_source_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            make_state(output_dir)

            original_pdf = output_dir / "subs" / "123 - Jane" / "submission.pdf"
            original_pdf.parent.mkdir(parents=True, exist_ok=True)
            original_pdf.write_bytes(b"%PDF-1.4")

            edited_pdf = output_dir / "123 - Jane" / "submission.pdf"
            edited_pdf.parent.mkdir(parents=True, exist_ok=True)
            edited_pdf.write_bytes(b"%PDF-1.4")

            api = ReviewApi(output_dir)
            original_payload = api.get_submission("sub-1", document_source="original")
            edited_payload = api.get_submission("sub-1", document_source="edited")

            self.assertEqual(original_payload["document_source"], "original")
            self.assertEqual(edited_payload["document_source"], "edited")
            self.assertEqual(original_payload["documents"][0]["path"], str(original_pdf))
            self.assertEqual(edited_payload["documents"][0]["path"], str(edited_pdf))
            self.assertTrue(original_payload["documents"][0]["exists"])
            self.assertTrue(edited_payload["documents"][0]["exists"])

    def test_get_submission_rejects_invalid_document_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            make_state(output_dir)
            api = ReviewApi(output_dir)

            with self.assertRaises(ReviewApiError):
                api.get_submission("sub-1", document_source="nope")

    def test_get_run_includes_deterministic_outcomes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            make_state(output_dir)

            (output_dir / "grading_diagnostics.json").write_text(
                json.dumps(
                    {
                        "totals": {
                            "submissions_processed": 1,
                            "success_count": 1,
                            "review_required_count": 0,
                            "failed_with_error_count": 0,
                            "warning_count": 0,
                            "by_code": {
                                "context_cache_create_failed": 1,
                                "context_cache_bypassed": 1,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "grading_audit.csv").write_text(
                "folder,student_name,band,verdict,error\n"
                "123 - Jane,Jane,Check Plus,correct,\n",
                encoding="utf-8",
            )
            (output_dir / "brightspace_grades_import.csv").write_text(
                "Username,Assignment 1 Points Grade <Numeric MaxPoints:2>\n"
                "jane,\n",
                encoding="utf-8",
            )

            api = ReviewApi(output_dir)
            payload = api.get_run()
            outcomes = payload.get("outcomes", {})

            self.assertTrue(outcomes.get("available"))
            self.assertEqual(outcomes.get("submissions_processed"), 1)
            self.assertEqual(outcomes.get("success_count"), 1)
            self.assertEqual(outcomes.get("cache_warning_count"), 2)
            self.assertEqual(outcomes.get("unmatched_grade_rows"), 1)
            self.assertEqual(outcomes.get("band_counts", {}).get("Check Plus"), 1)
            self.assertEqual(outcomes.get("verdict_counts", {}).get("correct"), 1)

    def test_get_run_uses_grade_column_from_diagnostics_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            make_state(output_dir)

            (output_dir / "grading_diagnostics.json").write_text(
                json.dumps(
                    {
                        "args_snapshot": {
                            "grade_column": "Assignment 2 Points Grade",
                        },
                        "totals": {
                            "submissions_processed": 1,
                            "success_count": 1,
                            "review_required_count": 0,
                            "failed_with_error_count": 0,
                            "warning_count": 0,
                            "by_code": {},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "grading_audit.csv").write_text(
                "folder,student_name,band,verdict,error\n"
                "123 - Jane,Jane,Check Plus,correct,\n",
                encoding="utf-8",
            )
            (output_dir / "brightspace_grades_import.csv").write_text(
                "Username,Assignment 2 Points Grade <Numeric MaxPoints:2>\n"
                "jane,\n",
                encoding="utf-8",
            )

            api = ReviewApi(output_dir)
            payload = api.get_run()
            outcomes = payload.get("outcomes", {})
            self.assertEqual(outcomes.get("unmatched_grade_rows"), 1)

    def test_get_run_falls_back_to_assignment_n_points_grade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            make_state(output_dir)

            (output_dir / "grading_diagnostics.json").write_text(
                json.dumps(
                    {
                        "totals": {
                            "submissions_processed": 1,
                            "success_count": 1,
                            "review_required_count": 0,
                            "failed_with_error_count": 0,
                            "warning_count": 0,
                            "by_code": {},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "grading_audit.csv").write_text(
                "folder,student_name,band,verdict,error\n"
                "123 - Jane,Jane,Check Plus,correct,\n",
                encoding="utf-8",
            )
            (output_dir / "brightspace_grades_import.csv").write_text(
                "Username,Assignment 3 Points Grade <Numeric MaxPoints:3>\n"
                "jane,\n",
                encoding="utf-8",
            )

            api = ReviewApi(output_dir)
            payload = api.get_run()
            outcomes = payload.get("outcomes", {})
            self.assertEqual(outcomes.get("unmatched_grade_rows"), 1)


if __name__ == "__main__":
    unittest.main()
