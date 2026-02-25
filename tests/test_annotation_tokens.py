from __future__ import annotations

import unittest

from grader.annotate import build_anchor_tokens, should_render_question_marks


class AnnotationTokenTests(unittest.TestCase):
    def test_build_anchor_tokens_includes_defaults_and_literals(self) -> None:
        tokens = build_anchor_tokens(
            question_id="a",
            label_patterns=["a)", r"\ba\)", "Question A"],
            explicit_tokens=["(a)"],
        )
        normalized = [token.lower() for token in tokens]
        self.assertIn("(a)", normalized)
        self.assertIn("a)", normalized)
        self.assertIn("a.", normalized)
        self.assertIn("question a", normalized)

    def test_dry_run_render_policy_defaults_to_header_only(self) -> None:
        self.assertFalse(should_render_question_marks(dry_run=True, annotate_dry_run_marks=False))
        self.assertTrue(should_render_question_marks(dry_run=True, annotate_dry_run_marks=True))
        self.assertTrue(should_render_question_marks(dry_run=False, annotate_dry_run_marks=False))


if __name__ == "__main__":
    unittest.main()
