from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grader.workflow_detect import DetectedConfig, DetectedField, DiscoveryContext, detect_defaults
from grader.workflow_cli import main, resolve_available_port
from grader.workflow_profile import WorkflowProfileError, load_workflow_profile


@contextlib.contextmanager
def pushd(path: Path):
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def write_profile(path: Path, output_dir: str = "../outputs/a2") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
[grade]
submissions_dir = "../inputs/subs"
solutions_pdf = "../solutions/assignment2.pdf"
rubric_yaml = "../configs/assignment2.yaml"
grades_template_csv = "../imports/assignment2.csv"
grade_column = "Assignment 2 Points Grade"
output_dir = "{output_dir}"
""".strip()
        + "\n",
        encoding="utf-8",
    )


def write_valid_review_state(output_dir: Path) -> None:
    state_path = output_dir / "review" / "review_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        """
{
  "schema_version": 1,
  "run_metadata": {},
  "grading_context": {},
  "submissions": {}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def make_detected_config(root: Path, *, rubric_exists: bool = True) -> DetectedConfig:
    submissions_dir = root / "subs"
    solutions_pdf = root / "solutions.pdf"
    rubric_yaml = root / "configs" / "a2.yaml"
    template_csv = root / "template.csv"
    output_dir = root / "outputs" / "a2"
    downloads_dir = root / "Downloads"
    submissions_dir.mkdir(parents=True, exist_ok=True)
    solutions_pdf.write_bytes(b"%PDF-1.4")
    template_csv.write_text("OrgDefinedId,Assignment 2 Points Grade <Numeric MaxPoints:2>\n", encoding="utf-8")
    downloads_dir.mkdir(parents=True, exist_ok=True)
    if rubric_exists:
        rubric_yaml.parent.mkdir(parents=True, exist_ok=True)
        rubric_yaml.write_text(
            (
                "assignment_id: a2\n"
                "bands:\n"
                "  check_plus_min: 0.9\n"
                "  check_min: 0.7\n"
                "questions:\n"
                "  - id: a\n"
            ),
            encoding="utf-8",
        )

    context = DiscoveryContext(
        cwd=root.resolve(),
        profile_path=(root / ".manual_runs" / "profiles" / "a2.toml").resolve(),
        profile_name="a2",
        assignment_token="2",
        downloads_dir=downloads_dir.resolve(),
        recency_days=7,
    )
    return DetectedConfig(
        context=context,
        submissions_dir=DetectedField(
            value=submissions_dir.resolve(),
            source="recent_run",
            confidence=0.9,
            candidates=(submissions_dir.resolve(),),
        ),
        solutions_pdf=DetectedField(
            value=solutions_pdf.resolve(),
            source="recent_run",
            confidence=0.9,
            candidates=(solutions_pdf.resolve(),),
        ),
        rubric_yaml=DetectedField(
            value=rubric_yaml.resolve(),
            source="default",
            confidence=0.4,
            candidates=(rubric_yaml.resolve(),),
        ),
        grades_template_csv=DetectedField(
            value=template_csv.resolve(),
            source="downloads",
            confidence=0.7,
            candidates=(template_csv.resolve(),),
        ),
        grade_column=DetectedField(
            value="Assignment 2 Points Grade",
            source="template_inference",
            confidence=0.7,
            candidates=(
                "Assignment 2 Points Grade",
                "Assignment 2 Points Grade <Numeric MaxPoints:2>",
            ),
        ),
        output_dir=DetectedField(
            value=output_dir.resolve(),
            source="default",
            confidence=0.4,
            candidates=(output_dir.resolve(),),
        ),
        host=DetectedField(value="127.0.0.1", source="default", confidence=0.4, candidates=("127.0.0.1",)),
        port=DetectedField(value=8765, source="default", confidence=0.4, candidates=(8765,)),
        optional_grade_values={
            "grading_mode": "unified",
            "model": "gemini-3-flash-preview",
            "identifier_column": "OrgDefinedId",
            "context_cache": True,
            "context_cache_ttl_seconds": 86400,
            "plain": False,
        },
        prior_rubric_question_ids=("a", "b", "c"),
    )


class WorkflowCliTests(unittest.TestCase):
    def test_run_success_executes_grade_init_serve_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            write_profile(profile_path)
            output_dir = (profile_path.parent / "../outputs/a2").resolve()

            stdout = io.StringIO()
            with (
                pushd(root),
                patch("grader.workflow_cli.invoke_grading_main", return_value=0) as grade_mock,
                patch("grader.workflow_cli.initialize_review_state", return_value=output_dir / "review/review_state.json") as init_mock,
                patch("grader.workflow_cli.review_state_status", return_value=("valid", "")),
                patch("grader.workflow_cli.resolve_available_port", return_value=(8766, True)),
                patch("grader.workflow_cli.run_review_server", return_value=None) as serve_mock,
                patch("sys.stdout", stdout),
            ):
                exit_code = main(["run", "--profile", "a2"])

            self.assertEqual(exit_code, 0)
            grade_argv = grade_mock.call_args.args[0]
            self.assertIn("--submissions-dir", grade_argv)
            self.assertIn("--grade-column", grade_argv)
            self.assertIn("Assignment 2 Points Grade", grade_argv)
            self.assertIn("--grading-mode", grade_argv)
            self.assertIn("unified", grade_argv)
            init_mock.assert_called_once_with(output_dir=output_dir, rubric_yaml=None)
            serve_mock.assert_called_once_with(output_dir=output_dir, host="127.0.0.1", port=8766)

    def test_run_fail_fast_when_grading_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            write_profile(profile_path)

            with (
                pushd(root),
                patch("grader.workflow_cli.invoke_grading_main", return_value=2) as grade_mock,
                patch("grader.workflow_cli.initialize_review_state") as init_mock,
                patch("grader.workflow_cli.run_review_server") as serve_mock,
            ):
                exit_code = main(["run", "--profile", "a2"])

            self.assertEqual(exit_code, 2)
            grade_mock.assert_called_once()
            init_mock.assert_not_called()
            serve_mock.assert_not_called()

    def test_resolve_available_port_shifts_when_preferred_is_busy(self) -> None:
        with patch(
            "grader.workflow_cli.can_bind_port",
            side_effect=[False, True],
        ):
            port, shifted = resolve_available_port(host="127.0.0.1", preferred_port=8765, max_attempts=5)
        self.assertEqual(port, 8766)
        self.assertTrue(shifted)

    def test_serve_rejects_missing_review_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            write_profile(profile_path)

            stderr = io.StringIO()
            with (
                pushd(root),
                patch("grader.workflow_cli.run_review_server") as serve_mock,
                patch("sys.stderr", stderr),
            ):
                exit_code = main(["serve", "--profile", "a2"])

            self.assertEqual(exit_code, 2)
            self.assertIn("Review state invalid", stderr.getvalue())
            serve_mock.assert_not_called()

    def test_list_reports_valid_and_missing_review_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profiles_dir = root / ".manual_runs" / "profiles"
            write_profile(profiles_dir / "a1.toml", output_dir="../outputs/a1")
            write_profile(profiles_dir / "a2.toml", output_dir="../outputs/a2")

            write_valid_review_state((profiles_dir / "../outputs/a1").resolve())

            stdout = io.StringIO()
            with (
                pushd(root),
                patch("sys.stdout", stdout),
            ):
                exit_code = main(["list"])

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Workflow Profiles", rendered)
            self.assertIn("a1", rendered)
            self.assertIn("valid", rendered)
            self.assertIn("a2", rendered)
            self.assertIn("missing", rendered)

    def test_setup_creates_profile_and_starter_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submissions_dir = root / "subs"
            solutions_pdf = root / "solutions.pdf"
            template_csv = root / "template.csv"

            inputs = [
                str(submissions_dir),  # submissions_dir
                str(solutions_pdf),  # solutions_pdf
                "",  # rubric path (accept default: ./configs/a2.yaml)
                "",  # create starter rubric? (default yes)
                "",  # assignment id (default profile name)
                "",  # question ids (default list)
                str(template_csv),  # grades template csv
                "",  # grade column (default)
                "",  # output dir (default)
                "",  # host (default)
                "",  # port (default)
            ]

            with (
                pushd(root),
                patch("builtins.input", side_effect=inputs),
            ):
                exit_code = main(["setup", "--profile", "a2"])

            self.assertEqual(exit_code, 0)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            rubric_path = root / "configs" / "a2.yaml"
            self.assertTrue(profile_path.exists())
            self.assertTrue(rubric_path.exists())

            profile = load_workflow_profile("a2", cwd=root)
            self.assertEqual(profile.path, profile_path.resolve())
            self.assertEqual(profile.grade.rubric_yaml, rubric_path.resolve())
            self.assertEqual(profile.grade.grade_column, "Assignment 2 Points Grade")

    def test_quickstart_requires_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stderr = io.StringIO()
            with (
                pushd(root),
                patch("sys.stdin.isatty", return_value=False),
                patch("sys.stdout.isatty", return_value=False),
                patch("sys.stderr", stderr),
            ):
                exit_code = main(["quickstart", "--profile", "a2"])

            self.assertEqual(exit_code, 2)
            self.assertIn("requires an interactive terminal", stderr.getvalue())

    def test_quickstart_no_run_writes_profile_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            detected = make_detected_config(root)
            with (
                pushd(root),
                patch("grader.workflow_cli.detect_defaults", return_value=detected),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("builtins.input", side_effect=[""]),
                patch("grader.workflow_cli.invoke_grading_main") as grade_mock,
            ):
                exit_code = main(["quickstart", "--profile", "a2", "--no-run", "--overwrite"])

            self.assertEqual(exit_code, 0)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            self.assertTrue(profile_path.exists())
            profile = load_workflow_profile("a2", cwd=root)
            self.assertEqual(profile.grade.grade_column, "Assignment 2 Points Grade <Numeric MaxPoints:2>")
            grade_mock.assert_not_called()

    def test_quickstart_accept_all_writes_profile_and_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            detected = make_detected_config(root)
            output_dir = (root / "outputs" / "a2").resolve()

            with (
                pushd(root),
                patch("grader.workflow_cli.detect_defaults", return_value=detected),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("builtins.input", side_effect=[""]),
                patch("grader.workflow_cli.invoke_grading_main", return_value=0) as grade_mock,
                patch("grader.workflow_cli.initialize_review_state", return_value=output_dir / "review/review_state.json"),
                patch("grader.workflow_cli.review_state_status", return_value=("valid", "")),
                patch("grader.workflow_cli.resolve_available_port", return_value=(8765, False)),
                patch("grader.workflow_cli.run_review_server", return_value=None) as serve_mock,
            ):
                exit_code = main(["quickstart", "--profile", "a2", "--overwrite"])

            self.assertEqual(exit_code, 0)
            grade_mock.assert_called_once()
            serve_mock.assert_called_once()

    def test_run_missing_profile_bootstraps_via_quickstart_then_runs_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                pushd(root),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("grader.workflow_cli.prompt_missing_profile_bootstrap_choice", return_value="quickstart"),
                patch("grader.workflow_cli.quickstart_profile_interactive", return_value=0) as quickstart_mock,
                patch(
                    "grader.workflow_cli.run_from_profile",
                    side_effect=[WorkflowProfileError("Profile file not found: /tmp/missing"), 0],
                ) as run_mock,
            ):
                exit_code = main(["run", "--profile", "a9"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_mock.call_count, 2)
            quickstart_mock.assert_called_once_with(profile_spec="a9", overwrite=False, auto_run=False)

    def test_serve_missing_profile_bootstraps_via_quickstart_without_grading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                pushd(root),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("grader.workflow_cli.prompt_missing_profile_bootstrap_choice", return_value="quickstart"),
                patch("grader.workflow_cli.quickstart_profile_interactive", return_value=0) as quickstart_mock,
                patch(
                    "grader.workflow_cli.serve_from_profile",
                    side_effect=[WorkflowProfileError("Profile file not found: /tmp/missing"), 0],
                ) as serve_profile_mock,
                patch("grader.workflow_cli.invoke_grading_main") as grade_mock,
            ):
                exit_code = main(["serve", "--profile", "a9"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(serve_profile_mock.call_count, 2)
            quickstart_mock.assert_called_once_with(profile_spec="a9", overwrite=False, auto_run=False)
            grade_mock.assert_not_called()

    def test_no_command_non_tty_prints_help(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main([])
        self.assertEqual(exit_code, 2)

    def test_interactive_menu_selects_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / ".manual_runs" / "profiles"
            profile_dir.mkdir(parents=True, exist_ok=True)
            with (
                pushd(root),
                patch("grader.workflow_cli.is_interactive_terminal", return_value=True),
                patch("grader.workflow_cli.prompt_select", return_value=5) as select_mock,
                patch("grader.workflow_cli.list_profiles", return_value=0) as list_mock,
            ):
                exit_code = main([])

            self.assertEqual(exit_code, 0)
            select_mock.assert_called_once()
            list_mock.assert_called_once()

    def test_import_happy_path_copies_assets_into_data_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = root / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)

            subs_src = downloads / "Assignment 2 Download"
            subs_src.mkdir(parents=True, exist_ok=True)
            (subs_src / "123 - Jane Doe").mkdir(parents=True, exist_ok=True)
            (subs_src / "123 - Jane Doe" / "submission.pdf").write_bytes(b"%PDF-1.4")

            solutions_src = downloads / "solutions_a2.pdf"
            solutions_src.write_bytes(b"%PDF-1.4")

            grades_src = downloads / "grades_a2.csv"
            grades_src.write_text("OrgDefinedId,Assignment 2 Points Grade\n", encoding="utf-8")

            with (
                pushd(root),
                patch("grader.workflow_cli.is_interactive_terminal", return_value=False),
            ):
                exit_code = main(
                    [
                        "import",
                        "--profile",
                        "a2",
                        "--downloads-dir",
                        str(downloads),
                        "--data-root",
                        str(root / "data"),
                    ]
                )

            self.assertEqual(exit_code, 0)
            data_root = root / "data" / "a2"
            self.assertTrue((data_root / "submissions" / "123 - Jane Doe" / "submission.pdf").exists())
            self.assertTrue((data_root / "solutions.pdf").exists())
            self.assertTrue((data_root / "grades.csv").exists())

    def test_import_no_downloads_prints_guidance_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = root / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)

            stdout = io.StringIO()
            with (
                pushd(root),
                patch("grader.workflow_cli.is_interactive_terminal", return_value=False),
                patch("sys.stdout", stdout),
            ):
                exit_code = main(
                    [
                        "import",
                        "--profile",
                        "a2",
                        "--downloads-dir",
                        str(downloads),
                        "--data-root",
                        str(root / "data"),
                    ]
                )

            self.assertEqual(exit_code, 2)
            rendered = stdout.getvalue()
            self.assertIn("No recent submissions folder, solutions PDF, or grade CSV found", rendered)
            self.assertFalse((root / "data" / "a2").exists())

    def test_import_dry_run_does_not_create_data_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = root / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)

            subs_src = downloads / "Assignment 2 Download"
            subs_src.mkdir(parents=True, exist_ok=True)
            (subs_src / "123 - Jane Doe").mkdir(parents=True, exist_ok=True)
            (subs_src / "123 - Jane Doe" / "submission.pdf").write_bytes(b"%PDF-1.4")

            with (
                pushd(root),
                patch("grader.workflow_cli.is_interactive_terminal", return_value=False),
            ):
                exit_code = main(
                    [
                        "import",
                        "--profile",
                        "a2",
                        "--downloads-dir",
                        str(downloads),
                        "--data-root",
                        str(root / "data"),
                        "--dry-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse((root / "data" / "a2").exists())

    def test_quickstart_blank_environment_shows_guidance_and_calls_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            blank_detected = DetectedConfig(
                context=DiscoveryContext(
                    cwd=root.resolve(),
                    profile_path=(root / ".manual_runs" / "profiles" / "a2.toml").resolve(),
                    profile_name="a2",
                    assignment_token="2",
                    downloads_dir=(root / "Downloads").resolve(),
                    recency_days=7,
                ),
                submissions_dir=DetectedField(value=None, source="missing", confidence=0.0, candidates=()),
                solutions_pdf=DetectedField(value=None, source="missing", confidence=0.0, candidates=()),
                rubric_yaml=DetectedField(
                    value=None,
                    source="missing",
                    confidence=0.0,
                    candidates=(),
                ),
                grades_template_csv=DetectedField(value=None, source="missing", confidence=0.0, candidates=()),
                grade_column=DetectedField(
                    value="Assignment 2 Points Grade",
                    source="default",
                    confidence=0.35,
                    candidates=("Assignment 2 Points Grade",),
                ),
                output_dir=DetectedField(
                    value=(root / "outputs" / "a2").resolve(),
                    source="default",
                    confidence=0.4,
                    candidates=((root / "outputs" / "a2").resolve(),),
                ),
                host=DetectedField(value="127.0.0.1", source="default", confidence=0.4, candidates=("127.0.0.1",)),
                port=DetectedField(value=8765, source="default", confidence=0.4, candidates=(8765,)),
                optional_grade_values={},
                prior_rubric_question_ids=(),
            )

            with (
                pushd(root),
                patch("grader.workflow_cli.detect_defaults", return_value=blank_detected),
                patch("grader.workflow_cli.is_interactive_terminal", return_value=True),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("builtins.input", side_effect=[""]),  # Accept running setup wizard
                patch("grader.workflow_cli.setup_profile_interactive", return_value=0) as setup_mock,
            ):
                exit_code = main(["quickstart", "--profile", "a2", "--overwrite"])

            self.assertEqual(exit_code, 0)
            setup_mock.assert_called_once_with(profile_spec="a2", overwrite=False)


class WorkflowDetectDataTests(unittest.TestCase):
    def test_detect_defaults_prefers_data_directory_over_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # data/a2 subtree
            data_root = root / "data" / "a2"
            subs_dir = data_root / "submissions"
            subs_dir.mkdir(parents=True, exist_ok=True)
            (subs_dir / "123 - Jane Doe").mkdir(parents=True, exist_ok=True)
            (subs_dir / "123 - Jane Doe" / "submission.pdf").write_bytes(b"%PDF-1.4")

            solutions_pdf = data_root / "solutions.pdf"
            solutions_pdf.write_bytes(b"%PDF-1.4")

            grades_csv = data_root / "grades.csv"
            grades_csv.write_text("OrgDefinedId,Assignment 2 Points Grade\n", encoding="utf-8")

            detected = detect_defaults(profile_spec="a2", cwd=root)

            self.assertEqual(detected.submissions_dir.value, subs_dir.resolve())
            self.assertEqual(detected.submissions_dir.source, "data")
            self.assertEqual(detected.solutions_pdf.value, solutions_pdf.resolve())
            self.assertEqual(detected.solutions_pdf.source, "data")
            self.assertEqual(detected.grades_template_csv.value, grades_csv.resolve())
            self.assertEqual(detected.grades_template_csv.source, "data")


if __name__ == "__main__":
    unittest.main()
