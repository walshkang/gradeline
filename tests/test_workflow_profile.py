from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grader.workflow_profile import WorkflowProfileError, load_workflow_profile
from grader.defaults import DEFAULT_MODEL


def write_profile(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


class WorkflowProfileTests(unittest.TestCase):
    def test_loads_valid_profile_with_resolved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            write_profile(
                profile_path,
                """
[grade]
submissions_dir = "../inputs/subs"
solutions_pdf = "../solutions/assignment2.pdf"
rubric_yaml = "../../configs/assignment2.yaml"
grades_template_csv = "../imports/a2_template.csv"
grade_column = "Assignment 2 Points Grade"
output_dir = "../outputs/a2"
""",
            )

            profile = load_workflow_profile("a2", cwd=root)
            self.assertEqual(profile.name, "a2")
            self.assertEqual(profile.path, profile_path.resolve())
            self.assertEqual(profile.grade.submissions_dir, (profile_path.parent / "../inputs/subs").resolve())
            self.assertEqual(profile.grade.solutions_pdf, (profile_path.parent / "../solutions/assignment2.pdf").resolve())
            self.assertEqual(profile.grade.grading_mode, "unified")
            self.assertEqual(profile.grade.model, DEFAULT_MODEL)
            self.assertEqual(profile.review.host, "127.0.0.1")
            self.assertEqual(profile.review.port, 8765)

    def test_missing_required_key_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            write_profile(
                profile_path,
                """
[grade]
submissions_dir = "/tmp/subs"
solutions_pdf = "/tmp/solutions.pdf"
rubric_yaml = "/tmp/rubric.yaml"
grades_template_csv = "/tmp/template.csv"
output_dir = "/tmp/out"
""",
            )

            with self.assertRaises(WorkflowProfileError):
                load_workflow_profile("a2", cwd=root)

    def test_unknown_grade_key_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            write_profile(
                profile_path,
                """
[grade]
submissions_dir = "/tmp/subs"
solutions_pdf = "/tmp/solutions.pdf"
rubric_yaml = "/tmp/rubric.yaml"
grades_template_csv = "/tmp/template.csv"
grade_column = "Assignment 2 Points Grade"
output_dir = "/tmp/out"
extra_key = "nope"
""",
            )

            with self.assertRaises(WorkflowProfileError) as ctx:
                load_workflow_profile("a2", cwd=root)
            self.assertIn("Unknown keys in [grade]", str(ctx.exception))

    def test_path_normalization_expands_env_and_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "fake-home"
            env_subs = root / "env-subs"
            env_subs.mkdir(parents=True, exist_ok=True)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            write_profile(
                profile_path,
                """
[grade]
submissions_dir = "$WF_SUBMISSIONS"
solutions_pdf = "~/solutions/assignment2.pdf"
rubric_yaml = "/tmp/rubric.yaml"
grades_template_csv = "/tmp/template.csv"
grade_column = "Assignment 2 Points Grade"
output_dir = "/tmp/out"
""",
            )

            with patch.dict(os.environ, {"WF_SUBMISSIONS": str(env_subs), "HOME": str(home)}, clear=False):
                profile = load_workflow_profile("a2", cwd=root)

            self.assertEqual(profile.grade.submissions_dir, env_subs.resolve())
            self.assertEqual(profile.grade.solutions_pdf, (home / "solutions/assignment2.pdf").resolve())

    def test_defaults_are_applied_for_optional_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / ".manual_runs" / "profiles" / "a2.toml"
            write_profile(
                profile_path,
                """
[grade]
submissions_dir = "/tmp/subs"
solutions_pdf = "/tmp/solutions.pdf"
rubric_yaml = "/tmp/rubric.yaml"
grades_template_csv = "/tmp/template.csv"
grade_column = "Assignment 2 Points Grade"
output_dir = "/tmp/out"
""",
            )

            profile = load_workflow_profile("a2", cwd=root)
            self.assertEqual(profile.grade.identifier_column, "OrgDefinedId")
            self.assertEqual(profile.grade.context_cache_ttl_seconds, 86400)
            self.assertTrue(profile.grade.context_cache)
            self.assertFalse(profile.grade.dry_run)
            self.assertFalse(profile.grade.plain)


if __name__ == "__main__":
    unittest.main()
