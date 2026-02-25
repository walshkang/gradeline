from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grader.workflow_cli import main, resolve_available_port
from grader.workflow_profile import load_workflow_profile


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
            self.assertIn("name\toutput_dir\trubric_yaml\treview_state", rendered)
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


if __name__ == "__main__":
    unittest.main()
