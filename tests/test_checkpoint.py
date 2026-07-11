from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grader.types import SubmissionUnit, QuestionResult, GradeResult, SubmissionResult
from grader.checkpoint import (
    save_checkpoint,
    load_checkpoint,
    clear_checkpoint,
    compute_run_config_hash,
    get_checkpoint_path,
)


class TestCheckpoint(unittest.TestCase):
    def test_checkpoint_roundtrip_and_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            
            # Setup dummy paths for rubric and solutions
            rubric_yaml = out_dir / "rubric.yaml"
            rubric_yaml.write_text("assignment_id: hw1\nbands: {}\nquestions: []", encoding="utf-8")
            solutions_pdf = out_dir / "solutions.pdf"
            solutions_pdf.write_text("dummy solutions content", encoding="utf-8")
            
            config_hash = compute_run_config_hash(
                rubric_path=rubric_yaml,
                solutions_pdf=solutions_pdf,
                model="gemma4-31b-it",
                grading_mode="unified",
            )
            
            # Create a mock result
            sub_unit = SubmissionUnit(
                folder_path=out_dir / "Student1 - John Doe",
                folder_relpath=Path("Student1 - John Doe"),
                folder_token="student_token_123",
                student_name="John Doe",
                pdf_paths=[out_dir / "Student1 - John Doe" / "sub.pdf"],
            )
            
            q_res = QuestionResult(
                id="q1",
                verdict="correct",
                confidence=0.95,
                short_reason="perfect",
                evidence_quote="formula verified",
                grading_source="regex",
            )
            
            gr_res = GradeResult(
                percent=100.0,
                band="Check Plus",
                points="10",
                has_needs_review=False,
                per_question_scores={"q1": 10.0},
            )
            
            res = SubmissionResult(
                submission=sub_unit,
                question_results=[q_res],
                grade_result=gr_res,
                output_pdf_paths=[out_dir / "graded_sub.pdf"],
                extraction_sources={"sub.pdf": "native"},
                global_flags=[],
                error=None,
            )
            
            # Make a mock rolling snapshot
            class MockRolling:
                def __init__(self) -> None:
                    self.band_counts = {"Check Plus": 1}
                    self.failure_count = 0
                    self.submissions_done = 1
                    self.total_seconds = 10.0
                    self.mean_seconds = 10.0
                    self.eta_seconds = 0.0

            rolling = MockRolling()
            
            # Save Checkpoint
            checkpoint_file = save_checkpoint(
                output_dir=out_dir,
                results=[res],
                rolling=rolling,
                run_config_hash=config_hash,
                stop_reason="user_interrupt",
            )
            
            self.assertTrue(checkpoint_file.exists())
            self.assertEqual(checkpoint_file, get_checkpoint_path(out_dir))
            
            # Load Checkpoint with matching hash
            loaded = load_checkpoint(out_dir, expected_config_hash=config_hash)
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded.results), 1)
            self.assertEqual(loaded.stop_reason, "user_interrupt")
            self.assertEqual(loaded.completed_folders, {"student_token_123"})
            
            # Verify restored fields
            restored_res = loaded.results[0]
            self.assertEqual(restored_res.submission.student_name, "John Doe")
            self.assertEqual(restored_res.submission.folder_token, "student_token_123")
            self.assertEqual(restored_res.grade_result.band, "Check Plus")
            self.assertEqual(restored_res.question_results[0].short_reason, "perfect")
            self.assertEqual(restored_res.question_results[0].grading_source, "regex")
            
            # Load with mismatched expected hash (simulates rubric edit/model shift)
            mismatched = load_checkpoint(out_dir, expected_config_hash="different-hash")
            self.assertIsNone(mismatched)
            
            # Clear Checkpoint
            cleared = clear_checkpoint(out_dir)
            self.assertTrue(cleared)
            self.assertFalse(checkpoint_file.exists())
            
            # Second clear should return False
            self.assertFalse(clear_checkpoint(out_dir))
