from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from grader.cli import (
    build_annotation_progress_callback,
    build_grading_progress_callback,
    main,
)
from grader.types import (
    ExtractedPdf,
    QuestionResult,
    QuestionRubric,
    RubricConfig,
    SubmissionUnit,
)
from grader.ui import PlainConsoleUI, args_to_subtitle, create_console_ui


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


class CliUiTests(unittest.TestCase):
    def test_create_console_ui_falls_back_to_plain_when_rich_unavailable(self) -> None:
        ui = create_console_ui(force_plain=False, is_tty=True, rich_available=False)
        self.assertIsInstance(ui, PlainConsoleUI)

    def test_main_plain_outputs_summary_and_artifacts(self) -> None:
        rubric = make_rubric()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir = root / "subs"
            submissions_dir.mkdir()
            student_dir = submissions_dir / "123-456 - Jane Doe - Feb 24"
            student_dir.mkdir()
            student_pdf = student_dir / "submission.pdf"
            student_pdf.write_bytes(b"%PDF-1.4")

            solutions_pdf = root / "solutions.pdf"
            solutions_pdf.write_bytes(b"%PDF-1.4")
            rubric_yaml = root / "rubric.yaml"
            rubric_yaml.write_text("placeholder", encoding="utf-8")
            template_csv = root / "template.csv"
            template_csv.write_text("OrgDefinedId,Assignment 1 Points Grade\n123,\n", encoding="utf-8")
            output_dir = root / "out"

            unit = SubmissionUnit(
                folder_path=student_dir,
                folder_relpath=Path(student_dir.name),
                folder_token="123-456",
                student_name="Jane Doe",
                pdf_paths=[student_pdf],
            )

            def fake_extract(pdf_path: Path, temp_dir: Path, ocr_char_threshold: int) -> ExtractedPdf:
                return ExtractedPdf(
                    pdf_path=pdf_path,
                    blocks=[],
                    text="sample text",
                    source="pdftotext",
                    native_char_count=20,
                    ocr_char_count=0,
                )

            def fake_annotate(
                submission: SubmissionUnit,
                rubric: RubricConfig,
                question_results: list[QuestionResult],
                output_dir: Path,
                submissions_root: Path,
                final_band: str,
                dry_run: bool,
                annotate_dry_run_marks: bool,
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
                patch("grader.cli.write_grading_audit_csv", return_value=output_dir / "grading_audit.csv"),
                patch("grader.cli.write_review_queue_csv", return_value=output_dir / "review_queue.csv"),
                patch(
                    "grader.cli.write_brightspace_import_csv",
                    return_value=(output_dir / "brightspace_grades_import.csv", []),
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    [
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
                        "--dry-run",
                        "--plain",
                    ]
                )

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Run Summary", rendered)
            self.assertIn("Submissions processed: 1", rendered)
            self.assertIn("Grading audit CSV", rendered)
            self.assertIn("Diagnostics JSON", rendered)

            diagnostics_path = output_dir / "grading_diagnostics.json"
            self.assertTrue(diagnostics_path.exists())
            payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["totals"]["submissions_processed"], 1)

    def test_args_to_subtitle_includes_unified_cache_status(self) -> None:
        class Args:
            dry_run = False
            model = "gemini-3-flash-preview"
            grading_mode = "unified"
            context_cache = True
            locator_model = ""

        subtitle = args_to_subtitle(Args())
        self.assertIn("grading=unified", subtitle)
        self.assertIn("cache=on", subtitle)

    def test_annotation_progress_callback_formats_question_progress(self) -> None:
        captured: list[str] = []

        callback = build_annotation_progress_callback(captured.append, total_questions=7)
        self.assertIsNotNone(callback)
        assert callback is not None

        callback(3, 7, "1a")
        self.assertEqual(captured, ["annotating question 1a (3/7)"])

    def test_grading_progress_callback_formats_question_progress(self) -> None:
        captured: list[str] = []

        callback = build_grading_progress_callback(captured.append, total_questions=5)
        self.assertIsNotNone(callback)
        assert callback is not None

        callback(2, 5, "b")
        self.assertEqual(captured, ["grading question b (2/5)"])

    def test_section_heading_plain(self) -> None:
        ui = PlainConsoleUI()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            ui.section_heading("Grading")
        self.assertIn("--- Grading ---", stdout.getvalue())

    def test_submission_finished_uses_human_band_names(self) -> None:
        ui = PlainConsoleUI()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            ui.submission_finished(1, 5, "student-folder", band="CHECK_PLUS", had_error=False)
        rendered = stdout.getvalue()
        self.assertIn("Check+", rendered)
        self.assertNotIn("CHECK_PLUS", rendered)


class TrustUxTests(unittest.TestCase):
    def test_build_trust_rationale_correct_band_and_mix(self) -> None:
        from grader.cli import build_trust_rationale

        results = [
            QuestionResult(id="q1", verdict="correct", confidence=0.95, short_reason="ok", evidence_quote="e"),
            QuestionResult(id="q2", verdict="correct", confidence=0.90, short_reason="ok", evidence_quote="e"),
            QuestionResult(id="q3", verdict="incorrect", confidence=0.80, short_reason="wrong", evidence_quote="e"),
        ]
        rubric_bands = {"check_plus_min": 0.9, "check_min": 0.7}
        out = build_trust_rationale(results, 66.67, "CHECK_MINUS", rubric_bands, [])
        self.assertIn("Check−", out)
        self.assertIn("66.67%", out)
        self.assertIn("2✓", out)
        self.assertIn("1✗", out)
        self.assertIn("→Check", out)

    def test_build_trust_rationale_low_confidence_items(self) -> None:
        from grader.cli import build_trust_rationale

        results = [
            QuestionResult(id="q1", verdict="correct", confidence=0.95, short_reason="ok", evidence_quote="e"),
            QuestionResult(id="q2", verdict="partial", confidence=0.40, short_reason="maybe", evidence_quote="e"),
        ]
        rubric_bands = {"check_plus_min": 0.9, "check_min": 0.7}
        out = build_trust_rationale(results, 75.0, "CHECK", rubric_bands, [])
        self.assertIn("low-conf", out)
        self.assertIn("q2", out)

    def test_build_trust_rationale_flags(self) -> None:
        from grader.cli import build_trust_rationale

        results = [
            QuestionResult(id="q1", verdict="correct", confidence=0.95, short_reason="ok", evidence_quote="e"),
        ]
        rubric_bands = {"check_plus_min": 0.9, "check_min": 0.7}
        out = build_trust_rationale(results, 95.0, "CHECK_PLUS", rubric_bands, ["dry_run"])
        self.assertIn("flags:dry_run", out)

    def test_update_rolling_snapshot_accumulates(self) -> None:
        from grader.cli import RollingSnapshot, update_rolling_snapshot
        from grader.types import GradeResult, SubmissionResult, SubmissionUnit

        unit = SubmissionUnit(
            folder_path=Path("/tmp/s1"), folder_relpath=Path("s1"),
            folder_token="tok1", student_name="A", pdf_paths=[],
        )
        grade1 = GradeResult(percent=80.0, band="CHECK", points="8", has_needs_review=False, per_question_scores={})
        res1 = SubmissionResult(
            submission=unit, question_results=[], grade_result=grade1,
            output_pdf_paths=[], extraction_sources={}, global_flags=[],
        )
        grade2 = GradeResult(percent=60.0, band="CHECK_MINUS", points="6", has_needs_review=False, per_question_scores={})
        res2 = SubmissionResult(
            submission=unit, question_results=[], grade_result=grade2,
            output_pdf_paths=[], extraction_sources={}, global_flags=[],
        )

        snap1 = update_rolling_snapshot(None, res1, elapsed=2.0, remaining=4)
        snap2 = update_rolling_snapshot(snap1, res2, elapsed=4.0, remaining=3)

        self.assertEqual(snap2.submissions_done, 2)
        self.assertEqual(snap2.band_counts, {"CHECK": 1, "CHECK_MINUS": 1})
        self.assertAlmostEqual(snap2.mean_seconds, 3.0)
        self.assertAlmostEqual(snap2.eta_seconds, 9.0)

    def test_plain_submission_finished_prints_rationale(self) -> None:
        ui = PlainConsoleUI()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            ui.submission_finished(
                1, 5, "student-folder", band="CHECK", had_error=False,
                rationale="Check (78.50%) | 3✓ 0◐ 0✗ 0⟳",
                elapsed_seconds=2.5,
            )
        rendered = stdout.getvalue()
        self.assertIn("Check (78.50%) | 3✓ 0◐ 0✗ 0⟳", rendered)
        self.assertIn("2.5s", rendered)

    def test_plain_emit_summary_includes_distribution_and_timing(self) -> None:
        from grader.ui import RunSummary

        summary = RunSummary(
            submissions_processed=3, success_count=3, review_required_count=0,
            failed_with_error_count=0, warning_count=0,
            band_counts={"CHECK": 2, "CHECK_MINUS": 1},
            mean_seconds=3.5, total_seconds=10.5,
        )
        ui = PlainConsoleUI()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            ui.emit_summary(summary)
        rendered = stdout.getvalue()
        self.assertIn("Band distribution", rendered)
        self.assertIn("Mean time", rendered)
        self.assertIn("Total grading time", rendered)

    def test_stage_timing_duration(self) -> None:
        from grader.cli import StageTiming

        st = StageTiming(name="extract", start=100.0, end=102.5)
        self.assertAlmostEqual(st.duration, 2.5)

    def test_submission_telemetry_begin_end_stage(self) -> None:
        from grader.cli import SubmissionTelemetry

        tel = SubmissionTelemetry()
        tel.begin_stage("extract")
        tel.end_stage()
        self.assertEqual(len(tel.stages), 1)
        self.assertGreater(tel.stages[0].duration, 0.0)


if __name__ == "__main__":
    unittest.main()
