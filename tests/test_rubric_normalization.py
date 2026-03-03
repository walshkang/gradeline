from __future__ import annotations

import unittest

from grader.gemini_client import normalize_draft_rubric_payload


class DraftRubricNormalizationTests(unittest.TestCase):
    def test_messy_ids_normalize_to_stable_tokens(self) -> None:
        payload = {
            "assignment_id": "Assignment 3 ",
            "questions": [
                {"id": "Q1)", "scoring_rules": "Rule 1"},
                {"id": "(2)", "scoring_rules": "Rule 2"},
                {"id": " (a) ", "scoring_rules": "Rule 3"},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        ids = [q["id"] for q in normalized["questions"]]
        # We expect compact, lowercased tokens (e.g., "q1", "2", "a") without punctuation.
        self.assertIn("q1", ids)
        self.assertIn("2", ids)
        self.assertIn("a", ids)

    def test_missing_points_and_weight_default_to_equal_weights(self) -> None:
        payload = {
            "assignment_id": "test",
            "questions": [
                {"id": "1", "scoring_rules": "r1"},
                {"id": "2", "scoring_rules": "r2"},
                {"id": "3", "scoring_rules": "r3"},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        weights = [q["weight"] for q in normalized["questions"]]
        self.assertEqual(len(weights), 3)
        # All weights should be equal after renormalization.
        self.assertAlmostEqual(weights[0], weights[1], places=6)
        self.assertAlmostEqual(weights[1], weights[2], places=6)
        self.assertAlmostEqual(sum(weights), 1.0, places=6)

    def test_points_are_normalized_into_weights_summing_to_one(self) -> None:
        payload = {
            "assignment_id": "test",
            "questions": [
                {"id": "1", "points": 5, "scoring_rules": "r1"},
                {"id": "2", "points": 10, "scoring_rules": "r2"},
                {"id": "3", "points": 15, "scoring_rules": "r3"},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        weights = [q["weight"] for q in normalized["questions"]]
        self.assertAlmostEqual(sum(weights), 1.0, places=6)
        # Ratios should match 5:10:15 == 1:2:3.
        self.assertAlmostEqual(weights[1] / weights[0], 2.0, places=2)
        self.assertAlmostEqual(weights[2] / weights[0], 3.0, places=2)

    def test_label_patterns_and_notes_are_defaulted_when_missing(self) -> None:
        payload = {
            "assignment_id": "test",
            "questions": [
                {"id": "1", "scoring_rules": ""},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback")
        question = normalized["questions"][0]

        # scoring_rules should be defaulted when empty.
        self.assertEqual(question["scoring_rules"], "Define expected answer criteria.")
        # label_patterns should be synthesized from the id.
        self.assertEqual(question["label_patterns"], ["1)", "1.", "(1)"])
        # short_note_* should have friendly defaults.
        self.assertEqual(question["short_note_pass"], "Correct.")
        self.assertEqual(question["short_note_fail"], "Needs revision.")

    def test_bands_and_partial_credit_default_when_missing(self) -> None:
        payload = {
            "assignment_id": "",
            "questions": [
                {"id": "1", "scoring_rules": "r1"},
            ],
        }

        normalized = normalize_draft_rubric_payload(payload, assignment_id="fallback-assignment")
        self.assertEqual(normalized["assignment_id"], "fallback-assignment")
        self.assertEqual(normalized["bands"]["check_plus_min"], 0.90)
        self.assertEqual(normalized["bands"]["check_min"], 0.70)
        self.assertEqual(normalized["scoring_mode"], "equal_weights")
        self.assertAlmostEqual(normalized["partial_credit"], 0.5, places=6)


if __name__ == "__main__":
    unittest.main()

