from __future__ import annotations

import unittest

from grader.gemini_client import normalize_draft_rubric_payload


class DraftRubricNormalizationTests(unittest.TestCase):
    def test_messy_ids_normalize_to_stable_tokens(self) -> None:
        payload = {
            "assignment_id": "Assignment 3 ",
            "questions": [
                {"id": "Q1)", "scoring_rules": "Rule 1"},
                {"id": "(2)", "scoring_rules": "Rule 2"},
                {"id": " (a) ", "scoring_rules": "Rule 3"},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        ids = [q["id"] for q in normalized["questions"]]
        # We expect compact, lowercased tokens (e.g., "q1", "2", "a") without punctuation.
        self.assertIn("q1", ids)
        self.assertIn("2", ids)
        self.assertIn("a", ids)

    def test_missing_points_and_weight_default_to_equal_weights(self) -> None:
        payload = {
            "assignment_id": "test",
            "questions": [
                {"id": "1", "scoring_rules": "r1"},
                {"id": "2", "scoring_rules": "r2"},
                {"id": "3", "scoring_rules": "r3"},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        weights = [q["weight"] for q in normalized["questions"]]
        self.assertEqual(len(weights), 3)
        # All weights should be equal after renormalization.
        self.assertAlmostEqual(weights[0], weights[1], places=6)
        self.assertAlmostEqual(weights[1], weights[2], places=6)
        self.assertAlmostEqual(sum(weights), 1.0, places=6)

    def test_points_are_normalized_into_weights_summing_to_one(self) -> None:
        payload = {
            "assignment_id": "test",
            "questions": [
                {"id": "1", "points": 5, "scoring_rules": "r1"},
                {"id": "2", "points": 10, "scoring_rules": "r2"},
                {"id": "3", "points": 15, "scoring_rules": "r3"},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        weights = [q["weight"] for q in normalized["questions"]]
        self.assertAlmostEqual(sum(weights), 1.0, places=6)
        # Ratios should match 5:10:15 == 1:2:3.
        self.assertAlmostEqual(weights[1] / weights[0], 2.0, places=2)
        self.assertAlmostEqual(weights[2] / weights[0], 3.0, places=2)

    def test_label_patterns_and_notes_are_defaulted_when_missing(self) -> None:
        payload = {
            "assignment_id": "test",
            "questions": [
                {"id": "1", "scoring_rules": ""},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        question = normalized["questions"][0]

        # scoring_rules should be defaulted when empty.
        self.assertEqual(question["scoring_rules"], "Define expected answer criteria.")
        # label_patterns should be synthesized from the id.
        self.assertEqual(question["label_patterns"], ["1)", "1.", "(1)"])
        # short_note_* should have friendly defaults.
        self.assertEqual(question["short_note_pass"], "Correct.")
        self.assertEqual(question["short_note_fail"], "Needs revision.")

    def test_bands_and_partial_credit_default_when_missing(self) -> None:
        payload = {
            "assignment_id": "",
            "questions": [
                {"id": "1", "scoring_rules": "r1"},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback-assignment")
        self.assertEqual(normalized["assignment_id"], "fallback-assignment")
        self.assertEqual(normalized["bands"]["check_plus_min"], 0.90)
        self.assertEqual(normalized["bands"]["check_min"], 0.70)
        self.assertEqual(normalized["scoring_mode"], "equal_weights")
        self.assertAlmostEqual(normalized["partial_credit"], 0.5, places=6)


    def test_expected_answers_normalization_and_cache(self) -> None:
        from grader.gemini_client import rubric_to_cache_payload
        from grader.types import QuestionRubric, RubricConfig

        payload = {
            "assignment_id": "test",
            "questions": [
                {"id": "1", "scoring_rules": "r1", "expected_answers": ["493.*557"]},
                {"id": "2", "scoring_rules": "r2"},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        questions = normalized["questions"]
        self.assertEqual(questions[0]["expected_answers"], ["493.*557"])
        self.assertEqual(questions[1]["expected_answers"], [])

        # Test cache payload serialization
        rubric = RubricConfig(
            assignment_id="test",
            bands={"check_plus_min": 0.9, "check_min": 0.7},
            questions=[
                QuestionRubric(
                    id="1",
                    label_patterns=["1)"],
                    scoring_rules="r1",
                    short_note_pass="ok",
                    short_note_fail="fail",
                    expected_answers=["493.*557"],
                )
            ],
        )
        cache_payload = rubric_to_cache_payload(rubric)
        self.assertEqual(cache_payload["questions"][0]["expected_answers"], ["493.*557"])

    def test_load_rubric_accepts_str_and_path(self) -> None:
        from pathlib import Path
        import tempfile
        from grader.config import load_rubric

        rubric_content = """
assignment_id: test_assignment
scoring_mode: equal_weights
partial_credit: 0.5
bands:
  check_plus_min: 0.9
  check_min: 0.7
questions:
  - id: "1"
    scoring_rules: "Rule 1"
    short_note_pass: "OK"
    short_note_fail: "Check"
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "rubric.yaml"
            tmp_path.write_text(rubric_content, encoding="utf-8")

            # Load using Path
            rubric_from_path = load_rubric(tmp_path)
            self.assertEqual(rubric_from_path.assignment_id, "test_assignment")

            # Load using str
            rubric_from_str = load_rubric(str(tmp_path))
            self.assertEqual(rubric_from_str.assignment_id, "test_assignment")

    def test_expected_numeric_compilation_decimals_and_percentages(self) -> None:
        from pathlib import Path
        import tempfile
        import re
        from grader.config import load_rubric

        rubric_content = """
assignment_id: test_numeric
scoring_mode: equal_weights
partial_credit: 0.5
bands:
  check_plus_min: 0.9
  check_min: 0.7
questions:
  - id: "q1"
    scoring_rules: "Rule 1"
    short_note_pass: "OK"
    short_note_fail: "Check"
    expected_numeric:
      value: 0.0808
      tolerance: 0.001
      allow_percent: true
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "rubric.yaml"
            tmp_path.write_text(rubric_content, encoding="utf-8")
            rubric = load_rubric(tmp_path)

            q1 = rubric.questions[0]
            self.assertIsNotNone(q1.expected_numeric)
            self.assertEqual(q1.expected_numeric.value, 0.0808)
            self.assertEqual(q1.expected_numeric.tolerance, 0.001)
            self.assertTrue(q1.expected_numeric.allow_percent)

            # Test compiled regexes against candidate student answers
            # Should match standard decimals (0.0808, .0808, 0.081, 0.080)
            sample_answers = ["0.0808", ".0808", "0.081", "0.080", "8.08%", "8.1%"]
            for sample in sample_answers:
                matched = any(re.search(pat, sample, re.IGNORECASE) for pat in q1.expected_answers)
                self.assertTrue(matched, f"Expected sample answer '{sample}' to match compiled regexes: {q1.expected_answers}")

    def test_expected_numeric_coexists_with_expected_answers(self) -> None:
        from pathlib import Path
        import tempfile
        from grader.config import load_rubric

        rubric_content = """
assignment_id: test_coexist
scoring_mode: equal_weights
partial_credit: 0.5
bands:
  check_plus_min: 0.9
  check_min: 0.7
questions:
  - id: "q1"
    scoring_rules: "Rule 1"
    short_note_pass: "OK"
    short_note_fail: "Check"
    expected_numeric:
      value: 167.78
      tolerance: 0.05
      allow_percent: false
    expected_answers:
      - "exact_string_match"
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "rubric.yaml"
            tmp_path.write_text(rubric_content, encoding="utf-8")
            rubric = load_rubric(tmp_path)

            q1 = rubric.questions[0]
            self.assertIn("exact_string_match", q1.expected_answers)
            # Percentage forms should not be included since allow_percent is False
            for pat in q1.expected_answers:
                self.assertNotIn("%", pat)

    def test_normalize_draft_rubric_payload_preserves_expected_numeric(self) -> None:
        payload = {
            "assignment_id": "test",
            "questions": [
                {
                    "id": "1",
                    "scoring_rules": "r1",
                    "expected_numeric": {"value": 42.5, "tolerance": 0.5, "allow_percent": True},
                }
            ],
        }
        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        q = normalized["questions"][0]
        self.assertIn("expected_numeric", q)
        self.assertEqual(q["expected_numeric"]["value"], 42.5)
        self.assertEqual(q["expected_numeric"]["tolerance"], 0.5)


if __name__ == "__main__":
    unittest.main()


