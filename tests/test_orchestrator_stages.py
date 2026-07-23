from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from grader.orchestrator import GradingConfig, Orchestrator, RollingSnapshot
from grader.stages import (
    append_error,
    build_trust_rationale,
    process_student_annotation,
    process_student_grading,
    run_preprocess_task,
    summarize_results,
    update_rolling_snapshot,
    write_reports_and_conclude,
)
from grader.types import GradeResult, QuestionRubric, QuestionResult, SubmissionResult


class TestOrchestratorStages(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path("/tmp/test_orch_stages")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.ui_mock = MagicMock()
        q1 = QuestionRubric(
            id="q1",
            label_patterns=["q1"],
            scoring_rules="",
            short_note_pass="Pass",
            short_note_fail="Fail",
        )
        self.config = GradingConfig(
            submissions_root=self.tmp_dir,
            output_dir=self.tmp_dir,
            temp_dir=self.tmp_dir,
            ocr_char_threshold=50,
            rubric=MagicMock(bands={"Check+": 90.0}, questions=[q1]),
            rubric_yaml=self.tmp_dir / "rubric.yaml",
            solutions_text=None,
            solutions_pdf_path=self.tmp_dir / "sol.pdf",
            grade_points={},
            grader=None,
            grading_mode="unified",
            agent_type="simple",
            context_cache=False,
            context_cache_ttl_seconds=300,
            dry_run=True,
            locator_model="locator",
            annotate_dry_run_marks=False,
            extraction_model="extract",
            gemini_api_key=None,
            extract_blocks=False,
            diagnostics=None,
            rate_limiter=None,
            annotation_font_size=10.0,
        )

    def test_run_preprocess_task_success(self):
        unit = MagicMock()
        with patch("grader.stages.preprocessing_stage.get_or_compute_preprocessing") as mock_prep:
            mock_prep.return_value = ["extracted_pdf"]
            idx, res_unit, extracted, err = run_preprocess_task(1, unit, self.config, None)
            self.assertEqual(idx, 1)
            self.assertEqual(res_unit, unit)
            self.assertEqual(extracted, ["extracted_pdf"])
            self.assertIsNone(err)

    def test_run_preprocess_task_exception(self):
        unit = MagicMock()
        with patch("grader.stages.preprocessing_stage.get_or_compute_preprocessing") as mock_prep:
            mock_prep.side_effect = RuntimeError("OCR Failed")
            idx, res_unit, extracted, err = run_preprocess_task(1, unit, self.config, None)
            self.assertEqual(idx, 1)
            self.assertIsNone(extracted)
            self.assertIsInstance(err, RuntimeError)

    def test_process_student_grading_zero_trust_error(self):
        unit = MagicMock()
        unit.folder_path.name = "student_01"
        with patch("grader.orchestrator.grade_one_submission") as mock_grade:
            mock_grade.side_effect = RuntimeError("Corrupted file")
            idx, res, elapsed = process_student_grading(
                index=1,
                unit=unit,
                config=self.config,
                ui=self.ui_mock,
                total_units=1,
            )
            self.assertEqual(idx, 1)
            self.assertEqual(res.grade_result.band, "REVIEW_REQUIRED")
            self.assertTrue(res.grade_result.has_needs_review)
            self.assertIn("Corrupted file", res.error)

    def test_process_student_annotation(self):
        submission_unit = MagicMock()
        submission_unit.folder_path.name = "student_02"
        grade_res = GradeResult(percent=100.0, band="Check+", points="10/10", has_needs_review=False, per_question_scores={})
        sub_res = SubmissionResult(
            submission=submission_unit,
            question_results=[],
            grade_result=grade_res,
            output_pdf_paths=[],
            extraction_sources={},
            global_flags=[],
        )

        with patch("grader.orchestrator.annotate_submission_pdfs") as mock_ann:
            mock_ann.return_value = (["out.pdf"], [])
            res, rolling, completed = process_student_annotation(
                index=1,
                result=sub_res,
                sub_elapsed=1.5,
                config=self.config,
                ui=self.ui_mock,
                rolling=None,
                completed_submissions=0,
                total_units=1,
            )
            self.assertEqual(completed, 1)
            self.assertEqual(rolling.submissions_done, 1)
            self.assertEqual(res.output_pdf_paths, ["out.pdf"])

    def test_summarize_results_and_reports(self):
        grade_res = GradeResult(percent=90.0, band="Check+", points="9/10", has_needs_review=False, per_question_scores={})
        submission_unit = MagicMock()
        sub_res = SubmissionResult(
            submission=submission_unit,
            question_results=[],
            grade_result=grade_res,
            output_pdf_paths=[],
            extraction_sources={},
            global_flags=[],
        )
        summary = summarize_results([sub_res], warning_count=0, snapshot=None)
        self.assertEqual(summary.submissions_processed, 1)
        self.assertEqual(summary.success_count, 1)

        artifacts = {}
        with patch("grader.orchestrator.write_grading_audit_csv") as m1, \
             patch("grader.orchestrator.write_review_queue_csv") as m2, \
             patch("grader.orchestrator.write_brightspace_import_csv") as m3:
            m1.return_value = self.tmp_dir / "audit.csv"
            m2.return_value = self.tmp_dir / "review.csv"
            m3.return_value = (self.tmp_dir / "brightspace.csv", [])

            code = write_reports_and_conclude(
                config=self.config,
                ui=self.ui_mock,
                submission_results=[sub_res],
                artifacts=artifacts,
                rolling=None,
                diagnostics_path=self.tmp_dir / "diag.json",
            )
            self.assertEqual(code, 0)
            self.assertIn("Grading audit CSV", artifacts)


if __name__ == "__main__":
    unittest.main()
