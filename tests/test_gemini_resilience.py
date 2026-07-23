from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from grader.gemini_resilience import (
    GeminiCacheStore,
    acquire_rate_limit,
    call_with_backoff,
    compute_context_cache_key,
    compute_grade_cache_key,
    compute_unified_grade_cache_key,
    parse_json_maybe_fenced,
    response_text,
    should_retry,
    structured_response_payload,
    wait_for_file_active,
)
from grader.types import QuestionRubric, RubricConfig


def make_test_rubric() -> RubricConfig:
    return RubricConfig(
        assignment_id="resilience_test",
        bands={"check_plus_min": 0.9},
        questions=[
            QuestionRubric(
                id="q1",
                label_patterns=["1."],
                scoring_rules="",
                short_note_pass="ok",
                short_note_fail="check",
            )
        ],
        scoring_mode="equal_weights",
    )


class GeminiResilienceTests(unittest.TestCase):
    def test_call_with_backoff_success(self) -> None:
        calls = {"count": 0}

        def work() -> str:
            calls["count"] += 1
            if calls["count"] < 2:
                raise RuntimeError("503 Service Unavailable")
            return "done"

        with patch("grader.gemini_resilience.time.sleep", return_value=None):
            result = call_with_backoff(work, max_retries=3)
        self.assertEqual(result, "done")
        self.assertEqual(calls["count"], 2)

    def test_should_retry_identifies_transient_errors(self) -> None:
        self.assertTrue(should_retry(RuntimeError("HTTP 429 Too Many Requests")))
        self.assertTrue(should_retry(RuntimeError("503 Service Unavailable")))
        self.assertTrue(should_retry(TimeoutError("Connection timed out")))
        self.assertFalse(should_retry(ValueError("Invalid argument schema")))

    def test_wait_for_file_active_success(self) -> None:
        client = MagicMock()
        file_ref = MagicMock(name="files/123")
        file_ref.name = "files/123"

        active_file = MagicMock()
        active_file.state = "ACTIVE"
        client.files.get.return_value = active_file

        res = wait_for_file_active(client, file_ref)
        self.assertEqual(res, active_file)

    def test_parse_json_maybe_fenced(self) -> None:
        fenced = "```json\n{\"status\": \"ok\", \"score\": 10}\n```"
        parsed = parse_json_maybe_fenced(fenced)
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["score"], 10)

    def test_cache_store_grading_and_context_ops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GeminiCacheStore(cache_dir=Path(tmp_dir))
            
            store.set_grading_cache("key1", {"result": "pass"})
            self.assertEqual(store.get_grading_cache("key1"), {"result": "pass"})
            self.assertIsNone(store.get_grading_cache("nonexistent"))

            store.set_context_cache("ckey1", {"cache_name": "caches/abc", "expires_at": 9999999999})
            self.assertEqual(store.get_context_cache("ckey1")["cache_name"], "caches/abc")

            store.delete_context_cache("ckey1")
            self.assertIsNone(store.get_context_cache("ckey1"))

    def test_acquire_rate_limit(self) -> None:
        limiter = MagicMock()
        mock_limiter = MagicMock()
        limiter.get_limiter.return_value = mock_limiter

        acquire_rate_limit(limiter, "gemini-2.5-flash")
        limiter.get_limiter.assert_called_once_with("gemini-2.5-flash")
        mock_limiter.acquire.assert_called_once()
