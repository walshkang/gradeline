from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from grader.orchestrator import GradingConfig, Orchestrator
from grader.types import SubmissionUnit
from tests.test_score import make_rubric


class OrchestratorErrorTests(unittest.TestCase):
    @patch("grader.orchestrator.grade_one_submission")
    def test_orchestrator_unhandled_grading_error_generates_perfect_fallback(self, mock_grade_one):
        """
        Verify that an unhandled Exception within Orchestrator.process_student
        (like if grade_one_submission crashes unexpectedly) results in
        a deterministically built SubmissionResult via from_error,
        with a 0.0 grade and REVIEW_REQUIRED band.
        """
        # Mock grade_one_submission to raise an unhandled Exception
        mock_grade_one.side_effect = RuntimeError("Simulated OCR or LLM total crash")

        rubric = make_rubric()
        config = GradingConfig(
            submissions_root=Path("/fake"),
            output_dir=Path("/fake/out"),
            temp_dir=Path("/fake/tmp"),
            ocr_char_threshold=500,
            rubric=rubric,
            rubric_yaml=Path("fake_rubric.yaml"),
            solutions_text=None,
            solutions_pdf_path=Path("fake_sol.pdf"),
            grade_points={"REVIEW_REQUIRED": "0", "Check Plus": "100", "Check": "85", "Check Minus": "65"},
            grader=MagicMock(),
            grading_mode="legacy",
            agent_type="dummy",
            context_cache=False,
            context_cache_ttl_seconds=0,
            dry_run=False,
            locator_model="",
            annotate_dry_run_marks=False,
            extraction_model="test",
            gemini_api_key="test",
            extract_blocks=False,
            diagnostics=None,
            rate_limiter=None,
            annotation_font_size=12.0,
            concurrency=1,
            quiet=True,
        )
        
        ui_mock = MagicMock()
        orchestrator = Orchestrator(config=config, ui=ui_mock)

        unit = SubmissionUnit(
            folder_path=Path("/fake/student1"),
            folder_relpath=Path("student1"),
            folder_token="student1",
            student_name="Student One",
            pdf_paths=[Path("/fake/student1/test.pdf")],
        )

        # Call process_student
        idx, result, elapsed = orchestrator.process_student(0, unit)

        # Assert process_student caught the error and returned a properly formatted result
        self.assertEqual(idx, 0)
        self.assertTrue(result.error is not None)
        self.assertIn("Simulated OCR or LLM total crash", result.error)
        
        # All verdicts should be needs_review
        for qr in result.question_results:
            self.assertEqual(qr.verdict, "needs_review")
            self.assertEqual(qr.confidence, 0.0)

        # The grade should be 0 and REVIEW_REQUIRED
        self.assertEqual(result.grade_result.band, "REVIEW_REQUIRED")
        self.assertEqual(result.grade_result.percent, 0.0)
        self.assertEqual(result.grade_result.points, "0")


if __name__ == "__main__":
    unittest.main()
