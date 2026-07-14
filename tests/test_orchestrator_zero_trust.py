from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from grader.checkpoint import get_checkpoint_path
from grader.orchestrator import GradingConfig, Orchestrator
from grader.types import SubmissionUnit, ExtractedPdf, TextBlock, SubmissionResult, GradeResult
from grader.extract import run_subprocess_suppressed
from grader.rate_limit import DailyLimitExhausted
from tests.test_score import make_rubric


class TestOrchestratorZeroTrust(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_obj.name)

        self.submissions_dir = self.temp_dir / "submissions"
        self.submissions_dir.mkdir()
        self.output_dir = self.temp_dir / "output"
        self.output_dir.mkdir()
        self.tmp_grader = self.temp_dir / "tmp"
        self.tmp_grader.mkdir()

        # Write dummy PDF
        self.student_dir = self.submissions_dir / "Student1"
        self.student_dir.mkdir()
        self.pdf_file = self.student_dir / "homework.pdf"
        self.pdf_file.write_text("DUMMY PDF CONTENT", encoding="utf-8")

        # Write dummy template CSV
        self.template_csv = self.temp_dir / "template.csv"
        self.template_csv.write_text("OrgDefinedId,Grade,End-of-Line Indicator\nstudent1,,#\n", encoding="utf-8")

        self.rubric = make_rubric()

        # Submission Unit
        self.sub_unit = SubmissionUnit(
            folder_path=self.student_dir,
            folder_relpath=Path("Student1"),
            folder_token="student1",
            student_name="Student One",
            pdf_paths=[self.pdf_file],
        )

        self.config = GradingConfig(
            submissions_root=self.submissions_dir,
            output_dir=self.output_dir,
            temp_dir=self.tmp_grader,
            ocr_char_threshold=500,
            rubric=self.rubric,
            rubric_yaml=self.temp_dir / "rubric.yaml",
            solutions_text=None,
            solutions_pdf_path=self.temp_dir / "sol.pdf",
            grade_points={"REVIEW_REQUIRED": "0"},
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
            extract_blocks=True,
            diagnostics=MagicMock(),
            rate_limiter=None,
            annotation_font_size=12.0,
            concurrency=1,
            grades_template_csv=self.template_csv,
            quiet=True,
        )

    def tearDown(self) -> None:
        self.temp_dir_obj.cleanup()

    @patch("grader.orchestrator.save_checkpoint")
    @patch("grader.orchestrator.extract_pdf_text")
    @patch("grader.orchestrator.grade_one_submission")
    def test_zero_trust_unhandled_exception_in_process_student(
        self,
        mock_grade_one: MagicMock,
        mock_extract: MagicMock,
        mock_save_checkpoint: MagicMock,
    ) -> None:
        # Simulate extraction returning fine
        mock_extract.return_value = ExtractedPdf(
            pdf_path=self.pdf_file,
            blocks=[],
            text="Mocked Text",
            source="pdftotext",
            native_char_count=11,
            ocr_char_count=0,
        )

        # Simulate API unhandled failure (crash)
        mock_grade_one.side_effect = RuntimeError("Simulated API Crash")

        ui_mock = MagicMock()
        orchestrator = Orchestrator(config=self.config, ui=ui_mock)

        # Orchestrator should run and return 4 (failures present) instead of crashing
        exit_code = orchestrator.run([self.sub_unit])
        self.assertEqual(exit_code, 4)

        # Verify a result with error was appended
        self.assertEqual(len(orchestrator.submission_results), 1)
        res = orchestrator.submission_results[0]
        self.assertEqual(res.submission.folder_token, "student1")
        self.assertTrue(res.grade_result.has_needs_review)
        self.assertEqual(res.grade_result.band, "REVIEW_REQUIRED")
        self.assertIn("Simulated API Crash", res.error)

        # Verify incremental checkpoint was saved
        mock_save_checkpoint.assert_called()

    @patch("grader.orchestrator.save_checkpoint")
    @patch("grader.orchestrator.annotate_submission_pdfs")
    @patch("grader.orchestrator.extract_pdf_text")
    @patch("grader.orchestrator.grade_one_submission")
    def test_zero_trust_unhandled_exception_in_annotate_submission_pdfs(
        self,
        mock_grade_one: MagicMock,
        mock_extract: MagicMock,
        mock_annotate: MagicMock,
        mock_save_checkpoint: MagicMock,
    ) -> None:
        mock_extract.return_value = ExtractedPdf(
            pdf_path=self.pdf_file,
            blocks=[],
            text="Mocked Text",
            source="pdftotext",
            native_char_count=11,
            ocr_char_count=0,
        )

        # Normal grade result
        mock_grade_one.return_value = SubmissionResult(
            submission=self.sub_unit,
            question_results=[],
            grade_result=GradeResult(100.0, "Check Plus", "10", False, {}),
            output_pdf_paths=[],
            extraction_sources={},
            global_flags=[],
            error=None,
        )

        # Simulate unhandled annotation crash
        mock_annotate.side_effect = RuntimeError("Simulated Annotation Crash")

        ui_mock = MagicMock()
        orchestrator = Orchestrator(config=self.config, ui=ui_mock)

        # Orchestrator should run and return 4 (failures present) instead of crashing
        exit_code = orchestrator.run([self.sub_unit])
        self.assertEqual(exit_code, 4)

        # Verify a result with annotation error was appended
        self.assertEqual(len(orchestrator.submission_results), 1)
        res = orchestrator.submission_results[0]
        self.assertIn("Simulated Annotation Crash", res.error)

        # Verify incremental checkpoint was saved
        mock_save_checkpoint.assert_called()

    @patch("grader.orchestrator.extract_pdf_text")
    @patch("grader.orchestrator.grade_one_submission")
    def test_quota_exhaustion_halt_condition(
        self,
        mock_grade_one: MagicMock,
        mock_extract: MagicMock,
    ) -> None:
        mock_extract.return_value = ExtractedPdf(
            pdf_path=self.pdf_file,
            blocks=[],
            text="Mocked Text",
            source="pdftotext",
            native_char_count=11,
            ocr_char_count=0,
        )

        # Simulate persistent HTTP 429 rate limit error
        mock_grade_one.side_effect = RuntimeError("Google API: ResourceExhausted 429 Quota exceeded")

        ui_mock = MagicMock()
        orchestrator = Orchestrator(config=self.config, ui=ui_mock)

        # Orchestrator should catch 429, raise DailyLimitExhausted, halt grading loop, and return 5 (Daily API limit reached)
        exit_code = orchestrator.run([self.sub_unit])
        self.assertEqual(exit_code, 5)

        # Verify checkpoint was written
        checkpoint_file = get_checkpoint_path(self.output_dir)
        self.assertTrue(checkpoint_file.exists())
        checkpoint_data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        self.assertEqual(checkpoint_data["stop_reason"], "rate_limit_exhausted")

    def test_run_subprocess_suppressed(self) -> None:
        # Clear log if exists
        log_file = Path(".grader_tmp/diagnostics.log")
        if log_file.exists():
            log_file.unlink()

        # Run valid command: should succeed, no log written
        res = run_subprocess_suppressed(["echo", "hello"], check=True)
        self.assertEqual(res.stdout.strip(), "hello")
        self.assertFalse(log_file.exists())

        # Run invalid command: should fail, check=True raises CalledProcessError, log written
        with self.assertRaises(subprocess.CalledProcessError):
            run_subprocess_suppressed(["pdfinfo", "nonexistent_file_xyz.pdf"], check=True)

        self.assertTrue(log_file.exists())
        log_content = log_file.read_text(encoding="utf-8")
        self.assertIn("Command Failed: pdfinfo nonexistent_file_xyz.pdf", log_content)


if __name__ == "__main__":
    unittest.main()
