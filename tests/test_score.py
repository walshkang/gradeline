from __future__ import annotations

import unittest

from grader.score import score_submission
from grader.types import QuestionResult, QuestionRubric, RubricConfig


def make_rubric() -> RubricConfig:
    questions = [
        QuestionRubric(
            id=label,
            label_patterns=[f"{label})"],
            scoring_rules="",
            short_note_pass="ok",
            short_note_fail="check",
        )
        for label in ["a", "b", "c", "d", "e"]
    ]
    return RubricConfig(
        assignment_id="test",
        bands={"check_plus_min": 0.9, "check_min": 0.7},
        questions=questions,
        scoring_mode="equal_weights",
        partial_credit=0.5,
    )


class ScoreTests(unittest.TestCase):
    def test_thresholds(self) -> None:
        rubric = make_rubric()
        results = [
            QuestionResult(id="a", verdict="correct", confidence=1, short_reason="", evidence_quote=""),
            QuestionResult(id="b", verdict="correct", confidence=1, short_reason="", evidence_quote=""),
            QuestionResult(id="c", verdict="correct", confidence=1, short_reason="", evidence_quote=""),
            QuestionResult(id="d", verdict="correct", confidence=1, short_reason="", evidence_quote=""),
            QuestionResult(id="e", verdict="incorrect", confidence=1, short_reason="", evidence_quote=""),
        ]
        grade = score_submission(
            rubric=rubric,
            question_results=results,
            grade_points={"Check Plus": "100", "Check": "85", "Check Minus": "65", "REVIEW_REQUIRED": ""},
        )
        self.assertEqual(grade.band, "Check")
        self.assertAlmostEqual(grade.percent, 80.0)

    def test_needs_review_forces_review_required(self) -> None:
        rubric = make_rubric()
        results = [
            QuestionResult(id="a", verdict="needs_review", confidence=0, short_reason="", evidence_quote=""),
            QuestionResult(id="b", verdict="correct", confidence=1, short_reason="", evidence_quote=""),
            QuestionResult(id="c", verdict="correct", confidence=1, short_reason="", evidence_quote=""),
            QuestionResult(id="d", verdict="correct", confidence=1, short_reason="", evidence_quote=""),
            QuestionResult(id="e", verdict="correct", confidence=1, short_reason="", evidence_quote=""),
        ]
        grade = score_submission(
            rubric=rubric,
            question_results=results,
            grade_points={"Check Plus": "100", "Check": "85", "Check Minus": "65", "REVIEW_REQUIRED": ""},
        )
        self.assertEqual(grade.band, "REVIEW_REQUIRED")
        self.assertEqual(grade.points, "")


if __name__ == "__main__":
    unittest.main()

