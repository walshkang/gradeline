from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grader.gemini_client import (
    DETAIL_REASON_MAX_CHARS,
    DETAIL_REASON_MAX_WORDS,
    NUMERIC_EQUIVALENCE_RULE,
    SHORT_REASON_MAX_CHARS,
    build_context_system_instruction,
    build_legacy_grading_prompt,
    build_unified_grading_prompt,
    call_with_backoff,
    clamp_short_reason,
    compute_context_cache_key,
    derive_detail_reason,
    derive_short_reason,
    extract_detail_reason,
    extract_overflow_detail,
    normalize_feedback,
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

    def test_prompts_include_numeric_equivalence_rule(self) -> None:
        rubric = make_rubric()
        legacy = build_legacy_grading_prompt(
            submission_id="sub-1",
            rubric=rubric,
            solutions_text="Solution text",
            combined_text="Student text",
        )
        unified = build_unified_grading_prompt(
            submission_id="sub-1",
            rubric=rubric,
            pdf_paths=[Path("submission.pdf")],
        )
        context_system = build_context_system_instruction(rubric)

        self.assertIn(NUMERIC_EQUIVALENCE_RULE, legacy)
        self.assertIn(NUMERIC_EQUIVALENCE_RULE, unified)
        self.assertIn(NUMERIC_EQUIVALENCE_RULE, context_system)

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


class TwoTierFeedbackTests(unittest.TestCase):
    # -- clamp_short_reason --------------------------------------------------

    def test_clamp_short_reason_short_text_passes_through(self) -> None:
        text = "Show your work."
        self.assertEqual(clamp_short_reason(text), text)
        self.assertLessEqual(len(text), SHORT_REASON_MAX_CHARS)

    def test_clamp_short_reason_exact_limit_passes_through(self) -> None:
        text = "a" * SHORT_REASON_MAX_CHARS
        self.assertEqual(clamp_short_reason(text), text)

    def test_clamp_short_reason_long_text_clips_at_word_boundary(self) -> None:
        text = "Show the final probability value and add one line of support for your answer"
        result = clamp_short_reason(text)
        self.assertLessEqual(len(result), SHORT_REASON_MAX_CHARS)
        self.assertFalse(result.endswith(" "))
        self.assertTrue(text.startswith(result))

    # -- extract_detail_reason ------------------------------------------------

    def test_extract_detail_reason_empty_returns_empty(self) -> None:
        self.assertEqual(extract_detail_reason(""), "")
        self.assertEqual(extract_detail_reason(None), "")  # type: ignore[arg-type]

    def test_extract_detail_reason_sentinels_return_empty(self) -> None:
        for sentinel in ("n/a", "N/A", "na", "NA", "none", "None"):
            self.assertEqual(extract_detail_reason(sentinel), "", msg=f"sentinel={sentinel!r}")

    def test_extract_detail_reason_normal_text_passes(self) -> None:
        text = "Missing the derivation step for Bayes' theorem."
        self.assertEqual(extract_detail_reason(text), text)

    def test_extract_detail_reason_trims_excess_words(self) -> None:
        words = ["word"] * (DETAIL_REASON_MAX_WORDS + 10)
        text = " ".join(words)
        result = extract_detail_reason(text)
        self.assertLessEqual(len(result.split()), DETAIL_REASON_MAX_WORDS)

    def test_extract_detail_reason_trims_excess_chars(self) -> None:
        text = "abcdefgh " * 40  # 9 chars * 40 = 360 chars, within word limit
        result = extract_detail_reason(text)
        self.assertLessEqual(len(result), DETAIL_REASON_MAX_CHARS)

    # -- extract_overflow_detail ----------------------------------------------

    def test_extract_overflow_detail_remainder_extracted(self) -> None:
        short = "Show your work."
        raw = "Show your work. Include the derivation step."
        result = extract_overflow_detail(raw, short)
        self.assertEqual(result, "Include the derivation step.")

    def test_extract_overflow_detail_identical_returns_empty(self) -> None:
        text = "Show your work."
        self.assertEqual(extract_overflow_detail(text, text), "")

    def test_extract_overflow_detail_empty_returns_empty(self) -> None:
        self.assertEqual(extract_overflow_detail("", "anything"), "")
        self.assertEqual(extract_overflow_detail("", ""), "")

    # -- normalize_feedback via normalize_model_response ----------------------

    def test_normalize_correct_verdict_clears_reasons(self) -> None:
        rubric = make_rubric()
        payload = {
            "student_submission_id": "x",
            "questions": [
                {"id": "a", "verdict": "correct", "confidence": 0.95,
                 "short_reason": "Great job", "evidence_quote": ""},
            ],
            "global_flags": [],
        }
        normalized = normalize_model_response(payload, rubric)
        by_id = {item.id: item for item in normalized["questions"]}
        self.assertEqual(by_id["a"].short_reason, "")
        self.assertEqual(by_id["a"].detail_reason, "")

    def test_normalize_needs_review_returns_review_manually(self) -> None:
        rubric = make_rubric()
        payload = {
            "student_submission_id": "x",
            "questions": [
                {"id": "a", "verdict": "needs_review", "confidence": 0.3,
                 "short_reason": "unclear", "evidence_quote": ""},
            ],
            "global_flags": [],
        }
        normalized = normalize_model_response(payload, rubric)
        by_id = {item.id: item for item in normalized["questions"]}
        self.assertEqual(by_id["a"].short_reason, "Review manually.")
        self.assertEqual(by_id["a"].detail_reason, "")

    def test_normalize_incorrect_short_raw_gives_reason_no_detail(self) -> None:
        rubric = make_rubric()
        payload = {
            "student_submission_id": "x",
            "questions": [
                {"id": "a", "verdict": "incorrect", "confidence": 0.9,
                 "short_reason": "Show your work.", "evidence_quote": ""},
            ],
            "global_flags": [],
        }
        normalized = normalize_model_response(payload, rubric)
        by_id = {item.id: item for item in normalized["questions"]}
        self.assertEqual(by_id["a"].short_reason, "Show your work.")
        self.assertEqual(by_id["a"].detail_reason, "")

    def test_normalize_incorrect_long_raw_overflows_into_detail(self) -> None:
        rubric = make_rubric()
        long_reason = "Show your work. You need to include the full derivation for the probability calculation."
        payload = {
            "student_submission_id": "x",
            "questions": [
                {"id": "a", "verdict": "incorrect", "confidence": 0.9,
                 "short_reason": long_reason, "evidence_quote": ""},
            ],
            "global_flags": [],
        }
        normalized = normalize_model_response(payload, rubric)
        by_id = {item.id: item for item in normalized["questions"]}
        self.assertLessEqual(len(by_id["a"].short_reason), SHORT_REASON_MAX_CHARS)
        self.assertTrue(len(by_id["a"].detail_reason) > 0)

    # -- derive_short_reason --------------------------------------------------

    def test_derive_short_reason_third_person_falls_back(self) -> None:
        result = derive_short_reason(
            raw_short_reason="The student forgot to show the derivation.",
            fallback_fail_note="Show your derivation.",
        )
        self.assertEqual(result, "Show your derivation.")

    def test_derive_short_reason_good_second_person_clamped(self) -> None:
        raw = "Show the final probability value."
        result = derive_short_reason(
            raw_short_reason=raw,
            fallback_fail_note="check",
        )
        self.assertLessEqual(len(result), SHORT_REASON_MAX_CHARS)
        self.assertTrue(raw.startswith(result))


if __name__ == "__main__":
    unittest.main()
