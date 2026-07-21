from __future__ import annotations

import unittest
from pathlib import Path

from grader.config import load_rubric
from grader.gemini_client import (
    build_rubric_lines,
    normalize_draft_rubric_payload,
    rubric_to_cache_payload,
)
from grader.review.types import rubric_from_dict, rubric_to_dict
from grader.score import compute_criteria_partial_score, score_submission
from grader.types import QuestionResult, QuestionRubric, RubricConfig, ScoringCriterion


class ScoringCriteriaTests(unittest.TestCase):
    def test_load_rubric_with_scoring_criteria(self) -> None:
        """YAML with scoring_criteria parses correctly into ScoringCriterion dataclasses."""
        import tempfile

        yaml_content = """
assignment_id: "test_assignment"
scoring_mode: "equal_weights"
partial_credit: 0.5
bands:
  Check Plus: 1.0
  Check: 0.85
questions:
  - id: "q1"
    scoring_rules: "Evaluate hypergeometric formula"
    short_note_pass: "Correct"
    short_note_fail: "Incorrect"
    scoring_criteria:
      - requirement: "Correct formula setup"
        weight: 1.5
        partial_if: "Formula written with wrong numbers"
      - requirement: "Correct arithmetic"
        weight: 0.5
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            rubric = load_rubric(temp_path)
            self.assertEqual(len(rubric.questions), 1)
            q1 = rubric.questions[0]
            self.assertEqual(len(q1.scoring_criteria), 2)
            self.assertEqual(q1.scoring_criteria[0].requirement, "Correct formula setup")
            self.assertEqual(q1.scoring_criteria[0].weight, 1.5)
            self.assertEqual(q1.scoring_criteria[0].partial_if, "Formula written with wrong numbers")
            self.assertEqual(q1.scoring_criteria[1].requirement, "Correct arithmetic")
            self.assertEqual(q1.scoring_criteria[1].weight, 0.5)
            self.assertEqual(q1.scoring_criteria[1].partial_if, "")
        finally:
            temp_path.unlink()

    def test_load_rubric_without_scoring_criteria(self) -> None:
        """Rubric loading defaults scoring_criteria to an empty list without regression."""
        import tempfile

        yaml_content = """
assignment_id: "test_assignment"
bands:
  Check: 0.8
questions:
  - id: "1"
    scoring_rules: "Basic answer"
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            rubric = load_rubric(temp_path)
            self.assertEqual(rubric.questions[0].scoring_criteria, [])
        finally:
            temp_path.unlink()

    def test_load_rubric_invalid_criteria(self) -> None:
        """Empty requirement string in criterion raises ValueError."""
        import tempfile

        yaml_content = """
assignment_id: "test_assignment"
bands:
  Check: 0.8
questions:
  - id: "q1"
    scoring_rules: "Rule"
    scoring_criteria:
      - requirement: ""
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx:
                load_rubric(temp_path)
            self.assertIn("empty requirement", str(ctx.exception).lower())
        finally:
            temp_path.unlink()

    def test_build_rubric_lines_formatting(self) -> None:
        """build_rubric_lines formats structured criteria when present and omits when empty."""
        sc1 = ScoringCriterion(requirement="Setup formula", weight=1.0, partial_if="Formula ok")
        sc2 = ScoringCriterion(requirement="Calculation", weight=2.0)
        q_with = QuestionRubric(
            id="q1",
            label_patterns=["1)"],
            scoring_rules="Main rule",
            short_note_pass="OK",
            short_note_fail="Fail",
            scoring_criteria=[sc1, sc2],
        )
        q_without = QuestionRubric(
            id="q2",
            label_patterns=["2)"],
            scoring_rules="Simple rule",
            short_note_pass="OK",
            short_note_fail="Fail",
        )
        rubric = RubricConfig(
            assignment_id="test",
            bands={"Check": 0.8},
            questions=[q_with, q_without],
        )

        lines = build_rubric_lines(rubric)
        self.assertEqual(len(lines), 2)
        self.assertIn("Structured Scoring Criteria", lines[0])
        self.assertIn("1. [weight=1.0] Setup formula — Partial credit if: Formula ok", lines[0])
        self.assertIn("2. [weight=2.0] Calculation", lines[0])

        self.assertNotIn("Structured Scoring Criteria", lines[1])

    def test_rubric_to_cache_payload(self) -> None:
        """rubric_to_cache_payload serializes scoring_criteria correctly."""
        sc = ScoringCriterion(requirement="Proof step", weight=1.0, partial_if="Partial proof")
        q = QuestionRubric(
            id="1",
            label_patterns=[],
            scoring_rules="Rule",
            short_note_pass="OK",
            short_note_fail="Fail",
            scoring_criteria=[sc],
        )
        rubric = RubricConfig(assignment_id="test", bands={"Check": 0.8}, questions=[q])

        payload = rubric_to_cache_payload(rubric)
        criteria_payload = payload["questions"][0]["scoring_criteria"]
        self.assertEqual(len(criteria_payload), 1)
        self.assertEqual(criteria_payload[0]["requirement"], "Proof step")
        self.assertEqual(criteria_payload[0]["weight"], 1.0)
        self.assertEqual(criteria_payload[0]["partial_if"], "Partial proof")

    def test_normalize_draft_rubric_payload_criteria(self) -> None:
        """normalize_draft_rubric_payload includes valid criteria in normalized rubric payload."""
        draft = {
            "assignment_id": "draft_test",
            "questions": [
                {
                    "id": "1",
                    "scoring_rules": "Derived rules",
                    "scoring_criteria": [
                        {"requirement": "State hypothesis", "weight": 1.0},
                        {"requirement": "Compute test stat", "weight": 2.0, "partial_if": "Wrong sign"},
                    ],
                }
            ],
        }
        normalized = normalize_draft_rubric_payload(draft, assignment_id="fallback")
        q = normalized["questions"][0]
        self.assertIn("scoring_criteria", q)
        self.assertEqual(len(q["scoring_criteria"]), 2)
        self.assertEqual(q["scoring_criteria"][1]["partial_if"], "Wrong sign")

    def test_review_types_roundtrip(self) -> None:
        """rubric_to_dict and rubric_from_dict support full roundtrip serialization with criteria."""
        sc = ScoringCriterion(requirement="Diagram drawn", weight=0.5, partial_if="Rough sketch")
        q = QuestionRubric(
            id="q1",
            label_patterns=["1."],
            scoring_rules="Draw diagram",
            short_note_pass="OK",
            short_note_fail="Fail",
            scoring_criteria=[sc],
        )
        rubric = RubricConfig(assignment_id="test", bands={"Check": 0.8}, questions=[q])

        serialized = rubric_to_dict(rubric)
        deserialized = rubric_from_dict(serialized)

        self.assertEqual(len(deserialized.questions), 1)
        dq = deserialized.questions[0]
        self.assertEqual(len(dq.scoring_criteria), 1)
        self.assertEqual(dq.scoring_criteria[0].requirement, "Diagram drawn")
        self.assertEqual(dq.scoring_criteria[0].weight, 0.5)

    def test_compute_criteria_partial_score(self) -> None:
        """Dynamic partial credit calculation parses met criteria weights."""
        criteria = [
            ScoringCriterion(requirement="Setup", weight=1.0),
            ScoringCriterion(requirement="Formula", weight=1.0),
            ScoringCriterion(requirement="Final Answer", weight=2.0),
        ]
        # Total weight = 4.0

        # Criteria 1 and 2 met (weight 2.0 / 4.0 = 0.5)
        score1 = compute_criteria_partial_score("Criteria 1, 2 met; Criterion 3 unmet.", criteria, fallback=0.5)
        self.assertAlmostEqual(score1, 0.5)

        # Criteria 1 and 3 met (weight 3.0 / 4.0 = 0.75)
        score2 = compute_criteria_partial_score("Criteria 1 and 3 met.", criteria, fallback=0.5)
        self.assertAlmostEqual(score2, 0.75)

        # Criterion 3 met only (weight 2.0 / 4.0 = 0.5)
        score3 = compute_criteria_partial_score("Criterion 3 met.", criteria, fallback=0.5)
        self.assertAlmostEqual(score3, 0.5)

    def test_compute_criteria_partial_score_fallback(self) -> None:
        """Invalid or unparseable criteria outputs fall back cleanly to fallback score."""
        criteria = [
            ScoringCriterion(requirement="Step 1", weight=1.0),
            ScoringCriterion(requirement="Step 2", weight=1.0),
        ]

        # No criteria mentioned
        score_fallback = compute_criteria_partial_score("Partial credit awarded for work.", criteria, fallback=0.6)
        self.assertEqual(score_fallback, 0.6)

        # Out-of-bounds criteria index (e.g. 99)
        score_oob = compute_criteria_partial_score("Criterion 99 met.", criteria, fallback=0.6)
        self.assertEqual(score_oob, 0.6)

    def test_score_submission_integration(self) -> None:
        """score_submission applies criteria score for partial verdicts."""
        sc1 = ScoringCriterion(requirement="Step A", weight=1.0)
        sc2 = ScoringCriterion(requirement="Step B", weight=3.0)
        q = QuestionRubric(
            id="q1",
            label_patterns=["1)"],
            scoring_rules="Rule",
            short_note_pass="Pass",
            short_note_fail="Fail",
            scoring_criteria=[sc1, sc2],
        )
        rubric = RubricConfig(assignment_id="test", bands={"Check": 0.5}, questions=[q], partial_credit=0.5)

        result_partial = QuestionResult(
            id="q1",
            verdict="partial",
            confidence=90.0,
            short_reason="Step A correct",
            evidence_quote="Quote",
            logic_analysis="Criterion 1 met; Criterion 2 unmet.",
        )

        res = score_submission(rubric, [result_partial], {"Check": "100"})
        # Earned: criterion 1 (weight 1.0) out of total weight 4.0 -> 0.25 (25%)
        self.assertAlmostEqual(res.percent, 25.0)
        self.assertAlmostEqual(res.per_question_scores["q1"], 0.25)


if __name__ == "__main__":
    unittest.main()
