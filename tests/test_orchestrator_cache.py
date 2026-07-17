from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from grader.extract import (
    serialize_extracted_pdf,
    deserialize_extracted_pdf,
    EXTRACTION_VERSION,
)
from grader.orchestrator import GradingConfig, Orchestrator, compute_submission_pdf_hash
from grader.types import SubmissionUnit, ExtractedPdf, TextBlock, SubmissionResult, GradeResult
from tests.test_score import make_rubric


class TestOrchestratorCache(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_obj.name)
        
        self.submissions_dir = self.temp_dir / "submissions"
        self.submissions_dir.mkdir()
        self.output_dir = self.temp_dir / "output"
        self.output_dir.mkdir()
        self.cache_dir = self.temp_dir / "cache"
        self.cache_dir.mkdir()
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
        
    def tearDown(self) -> None:
        self.temp_dir_obj.cleanup()

    def test_serialization_roundtrip(self) -> None:
        block = TextBlock(
            id="p1_b1",
            text="Hello World",
            page=1,
            left=10.0,
            top=20.0,
            width=30.0,
            height=40.0,
            source="tesseract_tsv",
            confidence=95.0,
        )
        pdf = ExtractedPdf(
            pdf_path=Path("dummy/path.pdf"),
            blocks=[block],
            text="Hello World\n",
            source="ocr",
            native_char_count=0,
            ocr_char_count=11,
        )
        
        serialized = serialize_extracted_pdf(pdf)
        self.assertEqual(serialized["pdf_path"], "dummy/path.pdf")
        self.assertEqual(serialized["text"], "Hello World\n")
        self.assertEqual(len(serialized["blocks"]), 1)
        self.assertEqual(serialized["blocks"][0]["id"], "p1_b1")
        self.assertEqual(serialized["blocks"][0]["confidence"], 95.0)
        
        deserialized = deserialize_extracted_pdf(serialized)
        self.assertEqual(deserialized.pdf_path, Path("dummy/path.pdf"))
        self.assertEqual(deserialized.text, "Hello World\n")
        self.assertEqual(deserialized.source, "ocr")
        self.assertEqual(len(deserialized.blocks), 1)
        self.assertEqual(deserialized.blocks[0].id, "p1_b1")
        self.assertEqual(deserialized.blocks[0].confidence, 95.0)

    @patch("grader.orchestrator.annotate_submission_pdfs")
    @patch("grader.preprocessing.extract_pdf_text")
    @patch("grader.orchestrator.grade_one_submission")
    def test_orchestrator_caching_and_bypass(
        self,
        mock_grade_one: MagicMock,
        mock_extract: MagicMock,
        mock_annotate: MagicMock,
    ) -> None:
        mock_annotate.return_value = ([], [])
        # Mock extract_pdf_text to return a mock ExtractedPdf
        mock_extract.return_value = ExtractedPdf(
            pdf_path=self.pdf_file,
            blocks=[TextBlock(id="p1_b1", text="Mocked Text", page=1, left=0, top=0, width=10, height=10, source="test")],
            text="Mocked Text",
            source="pdftotext",
            native_char_count=11,
            ocr_char_count=0,
        )
        
        # Mock grade_one_submission
        sub_unit = SubmissionUnit(
            folder_path=self.student_dir,
            folder_relpath=Path("Student1"),
            folder_token="student1",
            student_name="Student One",
            pdf_paths=[self.pdf_file],
        )
        mock_grade_one.return_value = SubmissionResult(
            submission=sub_unit,
            question_results=[],
            grade_result=GradeResult(100.0, "Check Plus", "10", False, {}),
            output_pdf_paths=[],
            extraction_sources={},
            global_flags=[],
            error=None,
        )

        config = GradingConfig(
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
            diagnostics=None,
            rate_limiter=None,
            annotation_font_size=12.0,
            concurrency=2,
            cache_dir=self.cache_dir,
            grades_template_csv=self.template_csv,
            quiet=True,
        )
        
        ui_mock = MagicMock()
        orchestrator = Orchestrator(config=config, ui=ui_mock)
        
        # --- First run (empty cache) ---
        # Run orchestrator
        exit_code = orchestrator.run([sub_unit])
        self.assertEqual(exit_code, 0)
        
        # extract_pdf_text should be called
        self.assertEqual(mock_extract.call_count, 1)
        
        # Verify cache file was written
        pdf_hash = compute_submission_pdf_hash([self.pdf_file])
        composite_key = f"{pdf_hash}_{EXTRACTION_VERSION}"
        cache_file = self.cache_dir / "preprocessing" / f"{composite_key}.json"
        self.assertTrue(cache_file.exists())
        
        # Check cache file contents
        cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
        self.assertEqual(cache_data[0]["text"], "Mocked Text")
        
        # Reset mocks
        mock_extract.reset_mock()
        mock_grade_one.reset_mock()
        
        # --- Second run (cached) ---
        orchestrator_run2 = Orchestrator(config=config, ui=ui_mock)
        exit_code = orchestrator_run2.run([sub_unit])
        self.assertEqual(exit_code, 0)
        
        # extract_pdf_text should NOT be called (loaded from cache)
        mock_extract.assert_not_called()
        self.assertEqual(mock_grade_one.call_count, 1)
        
        # Verify pre_extracted was passed to grade_one_submission
        passed_pre_extracted = mock_grade_one.call_args[1].get("pre_extracted")
        self.assertIsNotNone(passed_pre_extracted)
        self.assertEqual(passed_pre_extracted[0].text, "Mocked Text")


if __name__ == "__main__":
    unittest.main()
