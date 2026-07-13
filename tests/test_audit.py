from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from grader.audit import Inconsistency, analyze_grading_audit
from grader.types import QuestionRubric, RubricConfig


def create_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        if not rows:
            f.write("")
            return
        writer = csv.writer(f)
        writer.writerow(
            [
                "folder",
                "student_name",
                "pdf_count",
                "pdfs",
                "percent",
                "band",
                "points",
                "question_id",
                "verdict",
                "grading_source",
                "confidence",
                "logic_analysis",
                "reason",
                "detail_reason",
                "evidence_quote",
                "source_file",
                "page_number",
                "coords_y",
                "coords_x",
                "placement_source",
                "error",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.get("folder", ""),
                    r.get("student_name", ""),
                    r.get("pdf_count", "1"),
                    r.get("pdfs", ""),
                    r.get("percent", "0.0"),
                    r.get("band", ""),
                    r.get("points", ""),
                    r.get("question_id", ""),
                    r.get("verdict", ""),
                    r.get("grading_source", "llm"),
                    r.get("confidence", "1.0"),
                    r.get("logic_analysis", ""),
                    r.get("reason", ""),
                    r.get("detail_reason", ""),
                    r.get("evidence_quote", ""),
                    r.get("source_file", ""),
                    r.get("page_number", ""),
                    r.get("coords_y", ""),
                    r.get("coords_x", ""),
                    r.get("placement_source", ""),
                    r.get("error", ""),
                ]
            )


class AuditTests(unittest.TestCase):
    def test_missing_or_empty_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            missing_csv = temp_path / "missing.csv"
            report = analyze_grading_audit(missing_csv)
            self.assertEqual(report.total_students, 0)
            self.assertEqual(report.total_questions, 0)
            self.assertEqual(len(report.question_stats), 0)

            empty_csv = temp_path / "empty.csv"
            create_csv(empty_csv, [])
            report2 = analyze_grading_audit(empty_csv)
            self.assertEqual(report2.total_students, 0)
            self.assertEqual(report2.total_questions, 0)

    def test_basic_stats_and_pass_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "audit.csv"
            rows = [
                # Student 1
                {"folder": "s1", "student_name": "S1", "percent": "75.0", "band": "Check", "question_id": "q1", "verdict": "correct", "grading_source": "llm"},
                {"folder": "s1", "student_name": "S1", "percent": "75.0", "band": "Check", "question_id": "q2", "verdict": "partial", "grading_source": "llm"},
                # Student 2
                {"folder": "s2", "student_name": "S2", "percent": "100.0", "band": "Check Plus", "question_id": "q1", "verdict": "rounding_error", "grading_source": "regex"},
                {"folder": "s2", "student_name": "S2", "percent": "100.0", "band": "Check Plus", "question_id": "q2", "verdict": "correct", "grading_source": "llm"},
            ]
            create_csv(csv_path, rows)
            report = analyze_grading_audit(csv_path)

            self.assertEqual(report.total_students, 2)
            self.assertEqual(report.total_questions, 2)
            self.assertEqual(report.band_counts, {"Check": 1, "Check Plus": 1})

            stats_map = {s.question_id: s for s in report.question_stats}
            self.assertIn("q1", stats_map)
            self.assertIn("q2", stats_map)

            # q1 has correct and rounding_error (both count as correct)
            self.assertEqual(stats_map["q1"].correct, 2)
            self.assertEqual(stats_map["q1"].pass_rate, 1.0)
            self.assertEqual(stats_map["q1"].regex_count, 1)
            self.assertEqual(stats_map["q1"].llm_count, 1)

            # q2 has partial and correct. pass_rate = (1 + 1 * 0.5) / 2 = 0.75
            self.assertEqual(stats_map["q2"].correct, 1)
            self.assertEqual(stats_map["q2"].partial, 1)
            self.assertEqual(stats_map["q2"].pass_rate, 0.75)

    def test_inconsistency_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "audit.csv"
            rows = [
                {"folder": "s1", "student_name": "Student A", "question_id": "q1", "verdict": "correct", "evidence_quote": "The result is 42."},
                {"folder": "s2", "student_name": "Student B", "question_id": "q1", "verdict": "incorrect", "evidence_quote": "the result is 42!"},
                {"folder": "s3", "student_name": "Student C", "question_id": "q1", "verdict": "correct", "evidence_quote": "different answer"},
            ]
            create_csv(csv_path, rows)
            report = analyze_grading_audit(csv_path)

            self.assertEqual(len(report.inconsistencies), 1)
            inc = report.inconsistencies[0]
            self.assertEqual(inc.question_id, "q1")
            self.assertEqual(inc.evidence_a, "the result is 42")
            self.assertEqual(inc.evidence_b, "the result is 42")
            # Order may depend on reading but we expect one to be A (correct) and one B (incorrect)
            self.assertSetEqual({inc.verdict_a, inc.verdict_b}, {"correct", "incorrect"})
            self.assertSetEqual({inc.student_a, inc.student_b}, {"Student A", "Student B"})

    def test_borderline_students_explicit_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "audit.csv"
            rows = [
                {"folder": "s1", "student_name": "Student A", "percent": "88.0", "band": "Check", "question_id": "q1", "verdict": "correct"},
                {"folder": "s2", "student_name": "Student B", "percent": "68.0", "band": "Check Minus", "question_id": "q1", "verdict": "correct"},
                {"folder": "s3", "student_name": "Student C", "percent": "92.0", "band": "Check Plus", "question_id": "q1", "verdict": "correct"},
            ]
            create_csv(csv_path, rows)

            rubric = RubricConfig(
                assignment_id="test",
                bands={"check_plus_min": 0.90, "check_min": 0.70},
                questions=[QuestionRubric(id="q1", label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail="")],
                scoring_mode="equal_weights",
                partial_credit=0.5,
            )

            report = analyze_grading_audit(csv_path, rubric=rubric)
            self.assertEqual(len(report.borderline_students), 2)

            borderline_map = {b.student_name: b for b in report.borderline_students}
            self.assertIn("Student A", borderline_map)
            self.assertIn("Student B", borderline_map)

            # Student A (88%) is borderline for Check Plus (90.0%). gap = 2.0
            self.assertEqual(borderline_map["Student A"].next_band, "Check Plus")
            self.assertEqual(borderline_map["Student A"].gap, 2.0)

            # Student B (68%) is borderline for Check (70.0%). gap = 2.0
            self.assertEqual(borderline_map["Student B"].next_band, "Check")
            self.assertEqual(borderline_map["Student B"].gap, 2.0)

    def test_borderline_students_inferred_from_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "audit.csv"
            rows = [
                {"folder": "s1", "student_name": "Student A", "percent": "90.0", "band": "Check Plus", "question_id": "q1", "verdict": "correct"},
                {"folder": "s2", "student_name": "Student B", "percent": "88.0", "band": "Check", "question_id": "q1", "verdict": "correct"},
                {"folder": "s3", "student_name": "Student C", "percent": "70.0", "band": "Check", "question_id": "q1", "verdict": "correct"},
                {"folder": "s4", "student_name": "Student D", "percent": "68.0", "band": "Check Minus", "question_id": "q1", "verdict": "correct"},
            ]
            create_csv(csv_path, rows)

            report = analyze_grading_audit(csv_path, rubric=None)
            self.assertEqual(len(report.borderline_students), 2)

            borderline_map = {b.student_name: b for b in report.borderline_students}
            self.assertIn("Student B", borderline_map)
            self.assertIn("Student D", borderline_map)

            # Inferred thresholds: Check Plus = 90.0, Check = 70.0
            self.assertEqual(borderline_map["Student B"].next_band, "Check Plus")
            self.assertEqual(borderline_map["Student B"].gap, 2.0)

            self.assertEqual(borderline_map["Student D"].next_band, "Check")
            self.assertEqual(borderline_map["Student D"].gap, 2.0)

    def test_regex_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "audit.csv"
            rows = [
                {"folder": "s1", "question_id": "q1", "verdict": "correct", "grading_source": "llm", "evidence_quote": "A"},
                {"folder": "s2", "question_id": "q1", "verdict": "correct", "grading_source": "llm", "evidence_quote": "B"},
                {"folder": "s3", "question_id": "q1", "verdict": "correct", "grading_source": "llm", "evidence_quote": "A"},
                # Not a regex candidate since q2 only has 2 LLM correct
                {"folder": "s1", "question_id": "q2", "verdict": "correct", "grading_source": "llm", "evidence_quote": "X"},
                {"folder": "s2", "question_id": "q2", "verdict": "correct", "grading_source": "llm", "evidence_quote": "Y"},
            ]
            create_csv(csv_path, rows)
            report = analyze_grading_audit(csv_path)

            self.assertEqual(len(report.regex_candidates), 1)
            cand = report.regex_candidates[0]
            self.assertEqual(cand.question_id, "q1")
            self.assertEqual(cand.llm_correct_count, 3)
            # Sample answers should be unique and sorted
            self.assertEqual(cand.sample_answers, ["A", "B"])

    def test_load_from_review_state_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = tmp_path / "audit.csv"
            rows = [
                {"folder": "s1", "student_name": "S1", "percent": "48.0", "band": "Fail", "question_id": "q1", "verdict": "partial"},
            ]
            create_csv(csv_path, rows)

            # Write review/review_state.json
            state_data = {
                "grading_context": {
                    "rubric": {
                        "partial_credit": 0.25,
                        "bands": {
                            "Pass": 0.50,
                            "Fail": 0.0,
                        },
                    }
                }
            }
            state_path = tmp_path / "review" / "review_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state_data), encoding="utf-8")

            report = analyze_grading_audit(csv_path)
            stats = report.question_stats[0]
            # pass rate: correct (0) + partial (1) * 0.25 = 0.25
            self.assertEqual(stats.pass_rate, 0.25)

            # S1 has 48%, next band is Pass (50.0%). gap = 2.0 -> borderline!
            self.assertEqual(len(report.borderline_students), 1)
            self.assertEqual(report.borderline_students[0].next_band, "Pass")

    def test_load_from_grading_diagnostics_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = tmp_path / "audit.csv"
            rows = [
                {"folder": "s1", "student_name": "S1", "percent": "48.0", "band": "Fail", "question_id": "q1", "verdict": "partial"},
            ]
            create_csv(csv_path, rows)

            # Create dummy rubric yaml
            rubric_yaml = tmp_path / "rubric.yaml"
            rubric_yaml.write_text(
                """
assignment_id: "test"
scoring_mode: "equal_weights"
partial_credit: 0.10
bands:
  Pass: 0.50
  Fail: 0.0
questions:
  - id: "q1"
    label_patterns: []
    scoring_rules: ""
    short_note_pass: ""
    short_note_fail: ""
""",
                encoding="utf-8",
            )

            # Create grading_diagnostics.json referencing the rubric
            diag_data = {
                "args_snapshot": {
                    "rubric_yaml": str(rubric_yaml),
                }
            }
            diag_path = tmp_path / "grading_diagnostics.json"
            diag_path.write_text(json.dumps(diag_data), encoding="utf-8")

            report = analyze_grading_audit(csv_path)
            stats = report.question_stats[0]
            # pass rate: correct (0) + partial (1) * 0.10 = 0.10
            self.assertAlmostEqual(stats.pass_rate, 0.10)

            # Borderline student checks: S1 (48.0%) -> Pass (50.0%) is borderline.
            self.assertEqual(len(report.borderline_students), 1)
            self.assertEqual(report.borderline_students[0].next_band, "Pass")
            self.assertAlmostEqual(report.borderline_students[0].gap, 2.0)
