from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from grader.cli import main
from grader.types import (
    ExtractedPdf,
    QuestionResult,
    QuestionRubric,
    RubricConfig,
    SubmissionUnit,
)


def make_rubric() -> RubricConfig:
    return RubricConfig(
        assignment_id="test",
        bands={"check_plus_min": 0.9, "check_min": 0.7},
        questions=[
            QuestionRubric(
                id="a",
                label_patterns=["a)"],
                scoring_rules="",
                short_note_pass="ok",
                short_note_fail="check",
            )
        ],
    )


def make_extracted(pdf_path: Path) -> ExtractedPdf:
    return ExtractedPdf(
        pdf_path=pdf_path,
        blocks=[],
        text="answer text",
        source="pdftotext",
        native_char_count=20,
        ocr_char_count=0,
    )


def make_unit(submissions_dir: Path, folder: str) -> SubmissionUnit:
    folder_path = submissions_dir / folder
    folder_path.mkdir(parents=True, exist_ok=True)
    pdf_path = folder_path / "submission.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    return SubmissionUnit(
        folder_path=folder_path,
        folder_relpath=Path(folder),
        folder_token=folder.split(" - ")[0],
        student_name=folder,
        pdf_paths=[pdf_path],
    )


class CliErrorTests(unittest.TestCase):
    def _make_required_paths(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        submissions_dir = root / "subs"
        submissions_dir.mkdir()
        solutions_pdf = root / "solutions.pdf"
        solutions_pdf.write_bytes(b"%PDF-1.4")
        rubric_yaml = root / "rubric.yaml"
        rubric_yaml.write_text("placeholder", encoding="utf-8")
        template_csv = root / "template.csv"
        template_csv.write_text("OrgDefinedId,Assignment 1 Points Grade\n123,\n", encoding="utf-8")
        output_dir = root / "out"
        return submissions_dir, solutions_pdf, rubric_yaml, template_csv, output_dir

    def _base_args(
        self,
        submissions_dir: Path,
        solutions_pdf: Path,
        rubric_yaml: Path,
        template_csv: Path,
        output_dir: Path,
    ) -> list[str]:
        return [
            "--submissions-dir",
            str(submissions_dir),
            "--solutions-pdf",
            str(solutions_pdf),
            "--rubric-yaml",
            str(rubric_yaml),
            "--grades-template-csv",
            str(template_csv),
            "--grade-column",
            "Assignment 1 Points Grade",
            "--output-dir",
            str(output_dir),
            "--plain",
        ]

    def test_preflight_failure_records_diagnostics_and_returns_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir, solutions_pdf, rubric_yaml, template_csv, output_dir = self._make_required_paths(root)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("grader.cli.ensure_binaries_present", return_value=["pdftotext"]),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    self._base_args(
                        submissions_dir,
                        solutions_pdf,
                        rubric_yaml,
                        template_csv,
                        output_dir,
                    )
                    + ["--grading-mode", "legacy"]
                )

            self.assertEqual(exit_code, 2)
            diagnostics_path = output_dir / "grading_diagnostics.json"
            self.assertTrue(diagnostics_path.exists())
            payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            codes = [event["code"] for event in payload["events"]]
            self.assertIn("preflight_missing_binaries", codes)

    def test_unified_mode_skips_binary_preflight(self) -> None:
        rubric = make_rubric()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir, solutions_pdf, rubric_yaml, template_csv, output_dir = self._make_required_paths(root)
            ensure_mock = Mock(return_value=["pdftotext"])
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("grader.cli.ensure_binaries_present", ensure_mock),
                patch("grader.cli.load_rubric", return_value=rubric),
                patch("grader.cli.discover_submission_units", return_value=[]),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    self._base_args(
                        submissions_dir,
                        solutions_pdf,
                        rubric_yaml,
                        template_csv,
                        output_dir,
                    )
                    + ["--grading-mode", "unified", "--dry-run"]
                )

            self.assertEqual(exit_code, 0)
            ensure_mock.assert_not_called()
            diagnostics_path = output_dir / "grading_diagnostics.json"
            payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            codes = [event["code"] for event in payload["events"]]
            self.assertNotIn("preflight_missing_binaries", codes)

    def test_grading_exception_continues_and_is_reported(self) -> None:
        rubric = make_rubric()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir, solutions_pdf, rubric_yaml, template_csv, output_dir = self._make_required_paths(root)
            unit1 = make_unit(submissions_dir, "111 - First Student")
            unit2 = make_unit(submissions_dir, "222 - Second Student")

            class FakeGrader:
                def __init__(self, api_key: str, model: str, cache_dir: Path) -> None:
                    self.api_key = api_key

                def grade_submission(self, submission_id, pdf_paths, combined_text, rubric, solutions_text):
                    if submission_id.startswith("111"):
                        raise RuntimeError("grading boom")
                    return [
                        QuestionResult(
                            id="a",
                            verdict="correct",
                            confidence=0.9,
                            short_reason="ok",
                            evidence_quote="e",
                        )
                    ], []

                def locate_answers_for_pdf(self, pdf_path, rubric, locator_model):
                    return []

            def fake_extract(pdf_path: Path, temp_dir: Path, ocr_char_threshold: int) -> ExtractedPdf:
                return make_extracted(pdf_path)

            def fake_annotate(
                submission: SubmissionUnit,
                rubric: RubricConfig,
                question_results: list[QuestionResult],
                block_registry: dict[str, object],
                output_dir: Path,
                submissions_root: Path,
                final_band: str,
                dry_run: bool,
                annotate_dry_run_marks: bool,
                annotation_font_size: float,
                progress_callback=None,
            ) -> tuple[list[Path], list[QuestionResult]]:
                return [output_dir / f"{submission.folder_path.name}.pdf"], question_results

            review_writer = Mock(return_value=output_dir / "review_queue.csv")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("grader.cli.ensure_binaries_present", return_value=[]),
                patch("grader.cli.load_rubric", return_value=rubric),
                patch("grader.cli.discover_submission_units", return_value=[unit1, unit2]),
                patch("grader.cli.parse_index_html", return_value=[]),
                patch("grader.cli.write_index_audit_csv", return_value=output_dir / "index_audit.csv"),
                patch("grader.cli.extract_pdf_text", side_effect=fake_extract),
                patch("grader.llm_factory.get_llm_provider", side_effect=lambda provider_name, api_key, model, cache_dir: FakeGrader(api_key, model, cache_dir)),
                patch("grader.cli.annotate_submission_pdfs", side_effect=fake_annotate),
                patch("grader.cli.write_grading_audit_csv", return_value=output_dir / "grading_audit.csv"),
                patch("grader.cli.write_review_queue_csv", review_writer),
                patch(
                    "grader.cli.write_brightspace_import_csv",
                    return_value=(output_dir / "brightspace_grades_import.csv", []),
                ),
                patch.dict("os.environ", {"GEMINI_API_KEY": "token"}, clear=False),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    self._base_args(
                        submissions_dir,
                        solutions_pdf,
                        rubric_yaml,
                        template_csv,
                        output_dir,
                    )
                )

            self.assertEqual(exit_code, 4)
            results = review_writer.call_args.args[1]
            self.assertTrue(any(result.error for result in results))

            diagnostics_path = output_dir / "grading_diagnostics.json"
            payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            codes = [event["code"] for event in payload["events"]]
            self.assertTrue(
                any(code in {"grading_failed", "unified_grading_failed"} for code in codes)
            )

    def test_locator_and_annotation_failures_are_categorized(self) -> None:
        rubric = make_rubric()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir, solutions_pdf, rubric_yaml, template_csv, output_dir = self._make_required_paths(root)
            unit = make_unit(submissions_dir, "333 - Locator Student")

            class FakeGrader:
                def __init__(self, api_key: str, model: str, cache_dir: Path) -> None:
                    self.api_key = api_key

                def grade_submission(self, submission_id, pdf_paths, combined_text, rubric, solutions_text):
                    return [
                        QuestionResult(
                            id="a",
                            verdict="correct",
                            confidence=0.9,
                            short_reason="ok",
                            evidence_quote="e",
                        )
                    ], []

                def locate_answers_for_pdf(self, pdf_path, rubric, locator_model):
                    raise RuntimeError("locator boom")

            def fake_extract(pdf_path: Path, temp_dir: Path, ocr_char_threshold: int) -> ExtractedPdf:
                return make_extracted(pdf_path)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("grader.cli.ensure_binaries_present", return_value=[]),
                patch("grader.cli.load_rubric", return_value=rubric),
                patch("grader.cli.discover_submission_units", return_value=[unit]),
                patch("grader.cli.parse_index_html", return_value=[]),
                patch("grader.cli.write_index_audit_csv", return_value=output_dir / "index_audit.csv"),
                patch("grader.cli.extract_pdf_text", side_effect=fake_extract),
                patch("grader.llm_factory.get_llm_provider", side_effect=lambda provider_name, api_key, model, cache_dir: FakeGrader(api_key, model, cache_dir)),
                patch("grader.cli.annotate_submission_pdfs", side_effect=RuntimeError("annotation boom")),
                patch("grader.cli.write_grading_audit_csv", return_value=output_dir / "grading_audit.csv"),
                patch("grader.cli.write_review_queue_csv", return_value=output_dir / "review_queue.csv"),
                patch(
                    "grader.cli.write_brightspace_import_csv",
                    return_value=(output_dir / "brightspace_grades_import.csv", []),
                ),
                patch.dict("os.environ", {"GEMINI_API_KEY": "token"}, clear=False),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    self._base_args(
                        submissions_dir,
                        solutions_pdf,
                        rubric_yaml,
                        template_csv,
                        output_dir,
                    )
                    + ["--locator-model", "gemini-3-flash-preview"]
                )

            self.assertEqual(exit_code, 4)
            diagnostics_path = output_dir / "grading_diagnostics.json"
            payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            codes = [event["code"] for event in payload["events"]]
            self.assertIn("locator_failed", codes)
            self.assertIn("annotation_failed", codes)

    def test_report_write_failure_is_fatal_and_recorded(self) -> None:
        rubric = make_rubric()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir, solutions_pdf, rubric_yaml, template_csv, output_dir = self._make_required_paths(root)
            unit = make_unit(submissions_dir, "444 - Report Student")

            def fake_extract(pdf_path: Path, temp_dir: Path, ocr_char_threshold: int) -> ExtractedPdf:
                return make_extracted(pdf_path)

            def fake_annotate(
                submission: SubmissionUnit,
                rubric: RubricConfig,
                question_results: list[QuestionResult],
                block_registry: dict[str, object],
                output_dir: Path,
                submissions_root: Path,
                final_band: str,
                dry_run: bool,
                annotate_dry_run_marks: bool,
                annotation_font_size: float,
                progress_callback=None,
            ) -> tuple[list[Path], list[QuestionResult]]:
                return [output_dir / f"{submission.folder_path.name}.pdf"], question_results

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("grader.cli.ensure_binaries_present", return_value=[]),
                patch("grader.cli.load_rubric", return_value=rubric),
                patch("grader.cli.discover_submission_units", return_value=[unit]),
                patch("grader.cli.parse_index_html", return_value=[]),
                patch("grader.cli.write_index_audit_csv", return_value=output_dir / "index_audit.csv"),
                patch("grader.cli.extract_pdf_text", side_effect=fake_extract),
                patch("grader.cli.annotate_submission_pdfs", side_effect=fake_annotate),
                patch("grader.cli.write_grading_audit_csv", side_effect=RuntimeError("audit csv boom")),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    self._base_args(
                        submissions_dir,
                        solutions_pdf,
                        rubric_yaml,
                        template_csv,
                        output_dir,
                    )
                    + ["--dry-run"]
                )

            self.assertEqual(exit_code, 1)
            diagnostics_path = output_dir / "grading_diagnostics.json"
            payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            codes = [event["code"] for event in payload["events"]]
            self.assertIn("report_write_failed", codes)

    def test_unified_schema_error_is_categorized(self) -> None:
        rubric = make_rubric()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir, solutions_pdf, rubric_yaml, template_csv, output_dir = self._make_required_paths(root)
            unit = make_unit(submissions_dir, "555 - Unified Schema")

            class FakeGrader:
                def __init__(self, api_key: str, model: str, cache_dir: Path) -> None:
                    self.api_key = api_key

                def grade_submission_unified(
                    self,
                    submission_id,
                    pdf_paths,
                    rubric,
                    solutions_pdf_path,
                    context_cache_enabled,
                    context_cache_ttl_seconds,
                    blocks=None,
                    **kwargs,
                ):
                    raise ValueError("bad structured output")

            def fake_annotate(
                submission: SubmissionUnit,
                rubric: RubricConfig,
                question_results: list[QuestionResult],
                block_registry: dict[str, object],
                output_dir: Path,
                submissions_root: Path,
                final_band: str,
                dry_run: bool,
                annotate_dry_run_marks: bool,
                annotation_font_size: float,
                progress_callback=None,
            ) -> tuple[list[Path], list[QuestionResult]]:
                return [output_dir / f"{submission.folder_path.name}.pdf"], question_results

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("grader.cli.load_rubric", return_value=rubric),
                patch("grader.cli.discover_submission_units", return_value=[unit]),
                patch("grader.cli.parse_index_html", return_value=[]),
                patch("grader.cli.write_index_audit_csv", return_value=output_dir / "index_audit.csv"),
                patch("grader.llm_factory.get_llm_provider", side_effect=lambda provider_name, api_key, model, cache_dir: FakeGrader(api_key, model, cache_dir)),
                patch("grader.cli.annotate_submission_pdfs", side_effect=fake_annotate),
                patch("grader.cli.write_grading_audit_csv", return_value=output_dir / "grading_audit.csv"),
                patch("grader.cli.write_review_queue_csv", return_value=output_dir / "review_queue.csv"),
                patch(
                    "grader.cli.write_brightspace_import_csv",
                    return_value=(output_dir / "brightspace_grades_import.csv", []),
                ),
                patch.dict("os.environ", {"GEMINI_API_KEY": "token"}, clear=False),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    self._base_args(
                        submissions_dir,
                        solutions_pdf,
                        rubric_yaml,
                        template_csv,
                        output_dir,
                    )
                    + ["--grading-mode", "unified", "--no-extract-blocks"]
                )

            self.assertEqual(exit_code, 4)
            diagnostics_path = output_dir / "grading_diagnostics.json"
            payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            codes = [event["code"] for event in payload["events"]]
            self.assertIn("unified_schema_invalid", codes)

    def test_unified_context_cache_flags_are_recorded(self) -> None:
        rubric = make_rubric()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir, solutions_pdf, rubric_yaml, template_csv, output_dir = self._make_required_paths(root)
            unit = make_unit(submissions_dir, "666 - Unified Cache")

            class FakeGrader:
                def __init__(self, api_key: str, model: str, cache_dir: Path) -> None:
                    self.api_key = api_key

                def grade_submission_unified(
                    self,
                    submission_id,
                    pdf_paths,
                    rubric,
                    solutions_pdf_path,
                    context_cache_enabled,
                    context_cache_ttl_seconds,
                    blocks=None,
                    **kwargs,
                ):
                    return [
                        QuestionResult(
                            id="a",
                            verdict="correct",
                            confidence=0.95,
                            short_reason="ok",
                            evidence_quote="e",
                        )
                    ], [
                        "context_cache_lookup_failed",
                        "context_cache_create_failed",
                        "context_cache_bypassed",
                    ]

            def fake_annotate(
                submission: SubmissionUnit,
                rubric: RubricConfig,
                question_results: list[QuestionResult],
                block_registry: dict[str, object],
                output_dir: Path,
                submissions_root: Path,
                final_band: str,
                dry_run: bool,
                annotate_dry_run_marks: bool,
                annotation_font_size: float,
                progress_callback=None,
            ) -> tuple[list[Path], list[QuestionResult]]:
                return [output_dir / f"{submission.folder_path.name}.pdf"], question_results

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("grader.cli.load_rubric", return_value=rubric),
                patch("grader.cli.discover_submission_units", return_value=[unit]),
                patch("grader.cli.parse_index_html", return_value=[]),
                patch("grader.cli.write_index_audit_csv", return_value=output_dir / "index_audit.csv"),
                patch("grader.llm_factory.get_llm_provider", side_effect=lambda provider_name, api_key, model, cache_dir: FakeGrader(api_key, model, cache_dir)),
                patch("grader.cli.annotate_submission_pdfs", side_effect=fake_annotate),
                patch("grader.cli.write_grading_audit_csv", return_value=output_dir / "grading_audit.csv"),
                patch("grader.cli.write_review_queue_csv", return_value=output_dir / "review_queue.csv"),
                patch(
                    "grader.cli.write_brightspace_import_csv",
                    return_value=(output_dir / "brightspace_grades_import.csv", []),
                ),
                patch.dict("os.environ", {"GEMINI_API_KEY": "token"}, clear=False),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    self._base_args(
                        submissions_dir,
                        solutions_pdf,
                        rubric_yaml,
                        template_csv,
                        output_dir,
                    )
                    + ["--grading-mode", "unified", "--no-extract-blocks"]
                )

            self.assertEqual(exit_code, 0)
            diagnostics_path = output_dir / "grading_diagnostics.json"
            payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            codes = [event["code"] for event in payload["events"]]
            self.assertIn("context_cache_lookup_failed", codes)
            self.assertIn("context_cache_create_failed", codes)
            self.assertIn("context_cache_bypassed", codes)


if __name__ == "__main__":
    unittest.main()
