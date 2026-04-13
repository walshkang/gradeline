from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grader.diagnostics import DiagnosticsCollector


class DiagnosticsTests(unittest.TestCase):
    def test_writes_expected_payload_shape(self) -> None:
        collector = DiagnosticsCollector(args_snapshot={"dry_run": True, "model": "gemma4-31b-it"})
        collector.record(
            severity="warning",
            code="report_mapping_warning",
            stage="report_write",
            message="Identifier fallback used.",
        )
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            collector.record(
                severity="error",
                code="grading_failed",
                stage="grading",
                message="Gemini call failed.",
                submission_folder="student-1",
                exc=exc,
            )
        collector.set_run_totals({"submissions_processed": 2, "warning_count": 1})

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "grading_diagnostics.json"
            written = collector.write_json(out)
            payload = json.loads(written.read_text(encoding="utf-8"))

        self.assertEqual(payload["run_id"], collector.run_id)
        self.assertIn("started_at", payload)
        self.assertIn("ended_at", payload)
        self.assertEqual(payload["args_snapshot"]["dry_run"], True)
        self.assertEqual(payload["totals"]["submissions_processed"], 2)
        self.assertEqual(payload["totals"]["warning_count"], 1)
        self.assertEqual(payload["totals"]["by_code"]["grading_failed"], 1)
        self.assertEqual(len(payload["events"]), 2)
        self.assertEqual(payload["events"][1]["submission_folder"], "student-1")
        self.assertEqual(payload["events"][1]["exception_type"], "RuntimeError")

    def test_traceback_snippet_is_truncated(self) -> None:
        collector = DiagnosticsCollector(args_snapshot={})
        try:
            raise ValueError("x" * 200)
        except ValueError as exc:
            collector.record(
                severity="error",
                code="grading_failed",
                stage="grading",
                message="failed",
                exc=exc,
                traceback_limit=80,
            )

        self.assertEqual(len(collector.events), 1)
        snippet = collector.events[0].traceback_snippet
        self.assertIsNotNone(snippet)
        assert snippet is not None
        self.assertLessEqual(len(snippet), 80)


if __name__ == "__main__":
    unittest.main()
