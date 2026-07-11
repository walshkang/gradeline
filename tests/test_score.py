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

    def test_custom_dynamic_bands(self) -> None:
        questions = [
            QuestionRubric(id="a", label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail=""),
            QuestionRubric(id="b", label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail=""),
            QuestionRubric(id="c", label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail=""),
            QuestionRubric(id="d", label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail=""),
            QuestionRubric(id="e", label_patterns=[], scoring_rules="", short_note_pass="", short_note_fail=""),
        ]
        # Custom dynamic bands: 10 (100%), 9 (90%), 8 (80%), 7 (70%), 6 (60%), 5 (0%)
        rubric = RubricConfig(
            assignment_id="test_custom",
            bands={"10": 1.0, "9": 0.9, "8": 0.8, "7": 0.7, "6": 0.6, "5": 0.0},
            questions=questions,
            scoring_mode="equal_weights",
            partial_credit=0.5,
        )
        
        # 4 correct out of 5 -> 80% -> matches band "8"
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
            grade_points={"REVIEW_REQUIRED": ""},  # No custom mappings provided for "8", should fallback to "8"
        )
        self.assertEqual(grade.band, "8")
        self.assertEqual(grade.points, "8")
        self.assertEqual(grade.percent, 80.0)

    def test_empty_results_forces_review_required(self) -> None:
        rubric = make_rubric()
        grade = score_submission(
            rubric=rubric,
            question_results=[],
            grade_points={"Check Plus": "100", "Check": "85", "Check Minus": "65", "REVIEW_REQUIRED": ""},
        )
        self.assertEqual(grade.band, "REVIEW_REQUIRED")
        self.assertEqual(grade.points, "")
        self.assertTrue(grade.has_needs_review)

    def test_all_incorrect_results_gets_check_minus(self) -> None:
        rubric = make_rubric()
        results = [
            QuestionResult(id=label, verdict="incorrect", confidence=1, short_reason="", evidence_quote="")
            for label in ["a", "b", "c", "d", "e"]
        ]
        grade = score_submission(
            rubric=rubric,
            question_results=results,
            grade_points={"Check Plus": "100", "Check": "85", "Check Minus": "65", "REVIEW_REQUIRED": ""},
        )
        self.assertEqual(grade.band, "Check Minus")
        self.assertEqual(grade.points, "65")
        self.assertFalse(grade.has_needs_review)
        self.assertNotEqual(grade.band, "")


if __name__ == "__main__":
    unittest.main()


