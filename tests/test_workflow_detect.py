from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from grader.workflow_detect import (
    detect_defaults,
    find_recent_profile_runs,
    infer_grade_column_from_csv,
    infer_question_ids_from_prior_rubric,
    scan_downloads_candidates,
)


def write_profile(
    path: Path,
    *,
    submissions_dir: str,
    solutions_pdf: str,
    rubric_yaml: str,
    grades_template_csv: str,
    grade_column: str,
    output_dir: str,
    diagnostics_file: str | None = None,
) -> None:
    diagnostics_line = f'diagnostics_file = "{diagnostics_file}"\n' if diagnostics_file else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "[grade]\n"
            f'submissions_dir = "{submissions_dir}"\n'
            f'solutions_pdf = "{solutions_pdf}"\n'
            f'rubric_yaml = "{rubric_yaml}"\n'
            f'grades_template_csv = "{grades_template_csv}"\n'
            f'grade_column = "{grade_column}"\n'
            f'output_dir = "{output_dir}"\n'
            f"{diagnostics_line}"
            "\n"
            "[review]\n"
            'host = "127.0.0.1"\n'
            "port = 8765\n"
        ),
        encoding="utf-8",
    )


def write_diagnostics(
    path: Path,
    *,
    started_at: str,
    submissions_processed: int,
    success_count: int,
    failed_count: int,
    args_snapshot: dict[str, str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": started_at,
        "totals": {
            "submissions_processed": submissions_processed,
            "success_count": success_count,
            "failed_with_error_count": failed_count,
        },
        "args_snapshot": args_snapshot,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class WorkflowDetectTests(unittest.TestCase):
    def test_detect_defaults_uses_newest_successful_profile_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profiles = root / ".manual_runs" / "profiles"
            downloads = root / "Downloads"
            downloads.mkdir(parents=True)

            old_diag = root / "history" / "a1" / "grading_diagnostics.json"
            new_diag = root / "history" / "a2" / "grading_diagnostics.json"

            write_profile(
                profiles / "a1.toml",
                submissions_dir=str(root / "a1" / "subs"),
                solutions_pdf=str(root / "a1" / "solutions.pdf"),
                rubric_yaml=str(root / "a1" / "rubric.yaml"),
                grades_template_csv=str(root / "a1" / "template.csv"),
                grade_column="Assignment 1 Points Grade",
                output_dir=str(old_diag.parent),
            )
            write_profile(
                profiles / "a2.toml",
                submissions_dir=str(root / "a2" / "subs"),
                solutions_pdf=str(root / "a2" / "solutions.pdf"),
                rubric_yaml=str(root / "a2" / "rubric.yaml"),
                grades_template_csv=str(root / "a2" / "template.csv"),
                grade_column="Assignment 2 Points Grade",
                output_dir=str(new_diag.parent),
            )

            write_diagnostics(
                old_diag,
                started_at="2026-02-20T12:00:00Z",
                submissions_processed=10,
                success_count=8,
                failed_count=1,
                args_snapshot={
                    "submissions_dir": str(root / "history-old" / "submissions"),
                    "solutions_pdf": str(root / "history-old" / "solutions.pdf"),
                    "rubric_yaml": str(root / "history-old" / "rubric.yaml"),
                    "grades_template_csv": str(root / "history-old" / "template.csv"),
                    "grade_column": "Assignment 1 Points Grade",
                    "output_dir": str(root / "history-old" / "output"),
                },
            )
            write_diagnostics(
                new_diag,
                started_at="2026-02-24T12:00:00Z",
                submissions_processed=12,
                success_count=11,
                failed_count=0,
                args_snapshot={
                    "submissions_dir": str(root / "history-new" / "submissions"),
                    "solutions_pdf": str(root / "history-new" / "solutions.pdf"),
                    "rubric_yaml": str(root / "history-new" / "rubric.yaml"),
                    "grades_template_csv": str(root / "history-new" / "template.csv"),
                    "grade_column": "Assignment 2 Points Grade",
                    "output_dir": str(root / "history-new" / "output"),
                },
            )

            detected = detect_defaults(profile_spec="a3", cwd=root, downloads_dir=downloads)
            self.assertEqual(detected.submissions_dir.value, (root / "history-new" / "submissions").resolve())
            self.assertEqual(detected.solutions_pdf.value, (root / "history-new" / "solutions.pdf").resolve())
            self.assertEqual(detected.output_dir.value, (root / "history-new" / "output").resolve())

    def test_detect_defaults_prefers_existing_target_profile_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profiles = root / ".manual_runs" / "profiles"
            downloads = root / "Downloads"
            downloads.mkdir(parents=True)

            target_subs = root / "target_subs"
            target_solutions = root / "target_solutions.pdf"
            target_rubric = root / "configs" / "a2.yaml"
            target_template = root / "target_template.csv"
            target_output = root / "outputs" / "a2"
            target_template.write_text("OrgDefinedId,Assignment 2 Points Grade\n", encoding="utf-8")

            write_profile(
                profiles / "a2.toml",
                submissions_dir=str(target_subs),
                solutions_pdf=str(target_solutions),
                rubric_yaml=str(target_rubric),
                grades_template_csv=str(target_template),
                grade_column="Assignment 2 Points Grade",
                output_dir=str(target_output),
            )

            old_diag = root / "history" / "a1" / "grading_diagnostics.json"
            write_profile(
                profiles / "a1.toml",
                submissions_dir=str(root / "history" / "subs"),
                solutions_pdf=str(root / "history" / "solutions.pdf"),
                rubric_yaml=str(root / "history" / "rubric.yaml"),
                grades_template_csv=str(root / "history" / "template.csv"),
                grade_column="Assignment 1 Points Grade",
                output_dir=str(old_diag.parent),
            )
            write_diagnostics(
                old_diag,
                started_at="2026-02-24T12:00:00Z",
                submissions_processed=12,
                success_count=11,
                failed_count=0,
                args_snapshot={
                    "submissions_dir": str(root / "history" / "submissions"),
                    "solutions_pdf": str(root / "history" / "solutions.pdf"),
                    "rubric_yaml": str(root / "history" / "rubric.yaml"),
                    "grades_template_csv": str(root / "history" / "template.csv"),
                    "grade_column": "Assignment 1 Points Grade",
                    "output_dir": str(root / "history" / "output"),
                },
            )

            detected = detect_defaults(profile_spec="a2", cwd=root, downloads_dir=downloads)
            self.assertEqual(detected.submissions_dir.value, target_subs.resolve())
            self.assertEqual(detected.grade_column.value, "Assignment 2 Points Grade")

    def test_find_recent_profile_runs_uses_custom_diagnostics_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profiles = root / ".manual_runs" / "profiles"
            custom_diag = root / "diagnostics" / "a2.json"

            write_profile(
                profiles / "a2.toml",
                submissions_dir=str(root / "subs"),
                solutions_pdf=str(root / "solutions.pdf"),
                rubric_yaml=str(root / "rubric.yaml"),
                grades_template_csv=str(root / "template.csv"),
                grade_column="Assignment 2 Points Grade",
                output_dir=str(root / "out"),
                diagnostics_file=str(custom_diag),
            )
            write_diagnostics(
                custom_diag,
                started_at="2026-02-24T12:00:00Z",
                submissions_processed=3,
                success_count=2,
                failed_count=0,
                args_snapshot={"grade_column": "Assignment 2 Points Grade"},
            )

            snapshots = find_recent_profile_runs(cwd=root)
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].diagnostics_path, custom_diag.resolve())

    def test_scan_downloads_candidates_respects_recency_and_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / "Downloads"
            downloads.mkdir(parents=True)

            valid_dir = downloads / "Assignment 2 Download Feb 25"
            (valid_dir / "123 - Jane").mkdir(parents=True)
            (valid_dir / "123 - Jane" / "submission.pdf").write_bytes(b"%PDF-1.4")

            old_dir = downloads / "Assignment 2 Download Jan 01"
            (old_dir / "123 - Old").mkdir(parents=True)
            (old_dir / "123 - Old" / "submission.pdf").write_bytes(b"%PDF-1.4")
            old_timestamp = 1_700_000_000
            os.utime(old_dir, (old_timestamp, old_timestamp))

            (downloads / "notes").mkdir()

            csv_path = downloads / "SDA Grade CSV.csv"
            csv_path.write_text("OrgDefinedId,Assignment 2 Points Grade <Numeric MaxPoints:2>\n", encoding="utf-8")
            solution_path = downloads / "execDC24n2soln.pdf"
            solution_path.write_bytes(b"%PDF-1.4")

            candidates = scan_downloads_candidates(
                profile_name="a2",
                assignment_token="2",
                downloads_dir=downloads,
                recency_days=7,
            )
            self.assertIn(valid_dir.resolve(), candidates["submissions_dir"])
            self.assertNotIn(old_dir.resolve(), candidates["submissions_dir"])
            self.assertIn(csv_path.resolve(), candidates["grades_template_csv"])
            self.assertIn(solution_path.resolve(), candidates["solutions_pdf"])

    def test_infer_grade_column_from_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "template.csv"
            csv_path.write_text(
                "OrgDefinedId,Assignment 2 Points Grade <Numeric MaxPoints:2>,Feedback\n",
                encoding="utf-8",
            )
            inferred = infer_grade_column_from_csv(csv_path, assignment_token="2")
            self.assertEqual(inferred, "Assignment 2 Points Grade <Numeric MaxPoints:2>")

    def test_infer_question_ids_from_prior_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rubric_path = Path(tmp) / "a2.yaml"
            rubric_path.write_text(
                (
                    "assignment_id: a2\n"
                    "questions:\n"
                    "  - id: a\n"
                    "  - id: b\n"
                    "  - id: c\n"
                ),
                encoding="utf-8",
            )
            question_ids = infer_question_ids_from_prior_rubric(rubric_path)
            self.assertEqual(question_ids, ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
