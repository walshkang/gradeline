from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grader.gemini_client import (
    call_with_backoff,
    compute_context_cache_key,
    normalize_locator_response,
    normalize_model_response,
    parse_coords_0_to_1000,
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
        self.assertEqual(by_id["a"].short_reason, "")
        self.assertEqual(by_id["b"].verdict, "partial")
        self.assertEqual(by_id["c"].verdict, "needs_review")
        self.assertEqual(by_id["c"].short_reason, "Review manually.")
        self.assertEqual(normalized["global_flags"], ["flag1"])

    def test_reason_postprocessing_uses_sentence_and_fallbacks(self) -> None:
        rubric = make_rubric()
        payload = {
            "student_submission_id": "x",
            "questions": [
                {
                    "id": "a",
                    "verdict": "incorrect",
                    "confidence": 0.9,
                    "short_reason": "Show the final probability value. Add one line of support.",
                    "evidence_quote": "",
                },
                {
                    "id": "b",
                    "verdict": "partial",
                    "confidence": 0.6,
                    "short_reason": "The student did not show full work for the result and they need more supporting steps.",
                    "evidence_quote": "",
                },
                {
                    "id": "c",
                    "verdict": "needs_review",
                    "confidence": 0.2,
                    "short_reason": "unclear",
                    "evidence_quote": "",
                },
            ],
            "global_flags": [],
        }

        normalized = normalize_model_response(payload, rubric)
        by_id = {item.id: item for item in normalized["questions"]}
        self.assertEqual(by_id["a"].short_reason, "Show the final probability value.")
        self.assertEqual(by_id["b"].short_reason, "check")
        self.assertEqual(by_id["c"].short_reason, "Review manually.")

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

    def test_coords_bbox_is_converted_to_center(self) -> None:
        self.assertEqual(parse_coords_0_to_1000([100, 200, 300, 500]), (200.0, 350.0))

    def test_normalize_response_accepts_bbox_coords(self) -> None:
        rubric = make_rubric()
        payload = {
            "student_submission_id": "x",
            "questions": [
                {
                    "id": "a",
                    "verdict": "correct",
                    "confidence": 0.9,
                    "short_reason": "ok",
                    "evidence_quote": "e1",
                    "coords": [50, 100, 150, 300],
                }
            ],
            "global_flags": [],
        }
        normalized = normalize_model_response(payload, rubric)
        by_id = {item.id: item for item in normalized["questions"]}
        self.assertEqual(by_id["a"].coords, (100.0, 200.0))

    def test_context_cache_key_changes_with_rubric_and_solution_hash(self) -> None:
        rubric = make_rubric()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "solutions.pdf"
            path.write_bytes(b"%PDF-1.4\\nA")
            key1 = compute_context_cache_key(model="gemini-3-flash-preview", rubric=rubric, solutions_pdf_path=path)

            modified_rubric = RubricConfig(
                assignment_id=rubric.assignment_id,
                bands=rubric.bands,
                questions=[
                    QuestionRubric(
                        id=question.id,
                        label_patterns=question.label_patterns,
                        scoring_rules=question.scoring_rules + " changed",
                        short_note_pass=question.short_note_pass,
                        short_note_fail=question.short_note_fail,
                        weight=question.weight,
                        anchor_tokens=question.anchor_tokens,
                    )
                    for question in rubric.questions
                ],
                scoring_mode=rubric.scoring_mode,
                partial_credit=rubric.partial_credit,
            )
            key2 = compute_context_cache_key(
                model="gemini-3-flash-preview",
                rubric=modified_rubric,
                solutions_pdf_path=path,
            )
            self.assertNotEqual(key1, key2)

            path.write_bytes(b"%PDF-1.4\\nB")
            key3 = compute_context_cache_key(model="gemini-3-flash-preview", rubric=rubric, solutions_pdf_path=path)
            self.assertNotEqual(key1, key3)


if __name__ == "__main__":
    unittest.main()
