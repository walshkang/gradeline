from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grader.cost import TokenUsage
from grader.report import write_grading_audit_csv
from grader.review.api import ReviewApi
from grader.review.state import write_state_atomic
from grader.review.types import SCHEMA_VERSION, question_result_from_payload, question_result_to_payload
from grader.types import GradeResult, QuestionResult, SubmissionResult, SubmissionUnit


class TestTokenUsageTracking(unittest.TestCase):
    def test_question_result_payload_roundtrip(self) -> None:
        usage = TokenUsage(input_tokens=1500, output_tokens=300, cached_tokens=500, cost_usd=0.00015)
        qr = QuestionResult(
            id="q1",
            verdict="correct",
            confidence=1.0,
            short_reason="Good job",
            evidence_quote="Work shown",
            token_usage=usage,
        )
        payload = question_result_to_payload(qr)
        self.assertIn("token_usage", payload)
        self.assertEqual(payload["token_usage"]["input_tokens"], 1500)

        restored = question_result_from_payload("q1", payload)
        self.assertIsNotNone(restored.token_usage)
        self.assertEqual(restored.token_usage.input_tokens, 1500)
        self.assertEqual(restored.token_usage.output_tokens, 300)

    def test_grading_audit_csv_cost_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            usage = TokenUsage(input_tokens=2000, output_tokens=400, cached_tokens=1000, cost_usd=0.00025)
            unit = SubmissionUnit(
                folder_path=out_dir / "sub1",
                folder_relpath=Path("sub1"),
                folder_token="sub1",
                student_name="Jane Doe",
                pdf_paths=[out_dir / "sub1.pdf"],
            )
            q1 = QuestionResult(
                id="q1",
                verdict="correct",
                confidence=1.0,
                short_reason="OK",
                evidence_quote="",
                token_usage=usage,
            )
            sub_res = SubmissionResult(
                submission=unit,
                question_results=[q1],
                grade_result=GradeResult(
                    percent=100.0,
                    band="Check Plus",
                    points="100",
                    has_needs_review=False,
                    per_question_scores={"q1": 1.0},
                ),
                output_pdf_paths=[],
                extraction_sources={},
                global_flags=[],
            )

            audit_path = write_grading_audit_csv(out_dir, [sub_res])
            content = audit_path.read_text(encoding="utf-8")
            self.assertIn("input_tokens,output_tokens,cached_tokens,cost_usd", content)
            self.assertIn("2000,400,1000,0.000250", content)


if __name__ == "__main__":
    unittest.main()
