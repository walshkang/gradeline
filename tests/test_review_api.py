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


if __name__ == "__main__":
    unittest.main()
