from __future__ import annotations

import unittest
from unittest.mock import patch

from grader.gemini_client import (
    call_with_backoff,
    normalize_locator_response,
    normalize_model_response,
)
from grader.types import QuestionRubric, RubricConfig


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
    )


class GeminiContractTests(unittest.TestCase):
    def test_normalize_response_fills_missing_questions(self) -> None:
        rubric = make_rubric()
        payload = {
            "student_submission_id": "x",
            "questions": [
                {"id": "a", "verdict": "correct", "confidence": 0.9, "short_reason": "ok", "evidence_quote": "e1"},
                {"id": "b", "verdict": "partial", "confidence": 0.8, "short_reason": "partial", "evidence_quote": "e2"},
            ],
            "global_flags": ["flag1"],
        }
        normalized = normalize_model_response(payload, rubric)
        self.assertEqual(len(normalized["questions"]), 5)
        by_id = {item.id: item for item in normalized["questions"]}
        self.assertEqual(by_id["a"].verdict, "correct")
        self.assertEqual(by_id["b"].verdict, "partial")
        self.assertEqual(by_id["c"].verdict, "needs_review")
        self.assertEqual(normalized["global_flags"], ["flag1"])

    def test_backoff_retries_rate_limit(self) -> None:
        calls = {"count": 0}

        def flaky() -> str:
            calls["count"] += 1
            if calls["count"] < 3:
                raise RuntimeError("429 rate limit")
            return "ok"

        with patch("grader.gemini_client.time.sleep", return_value=None):
            result = call_with_backoff(flaky, max_retries=5)

        self.assertEqual(result, "ok")
        self.assertEqual(calls["count"], 3)

    def test_locator_results_schema_normalizes_coords(self) -> None:
        rubric = make_rubric()
        payload = {
            "results": [
                {
                    "q": "a",
                    "coords": [1200, -20],
                    "page_number": "2",
                    "source_file": "foo.pdf",
                    "confidence": 0.81,
                },
                {
                    "q": "z",
                    "coords": [200, 300],
                    "confidence": 0.2,
                },
            ]
        }
        normalized = normalize_locator_response(
            payload=payload,
            rubric=rubric,
            default_source_file="fallback.pdf",
        )
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["id"], "a")
        self.assertEqual(normalized[0]["coords"], (1000.0, 0.0))
        self.assertEqual(normalized[0]["page_number"], 2)
        self.assertEqual(normalized[0]["source_file"], "foo.pdf")


if __name__ == "__main__":
    unittest.main()
