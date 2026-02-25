from __future__ import annotations

import unittest
from pathlib import Path

from grader.cli import apply_locator_candidates
from grader.types import QuestionResult


class CliLocatorTests(unittest.TestCase):
    def test_merge_picks_highest_confidence_then_file_order(self) -> None:
        results = [
            QuestionResult(id="a", verdict="correct", confidence=0.9, short_reason="", evidence_quote=""),
            QuestionResult(id="b", verdict="incorrect", confidence=0.9, short_reason="", evidence_quote=""),
        ]
        candidates = {
            "a": [
                {"id": "a", "coords": (100.0, 200.0), "confidence": 0.80, "source_file": "first.pdf", "page_number": 1},
                {"id": "a", "coords": (300.0, 400.0), "confidence": 0.95, "source_file": "second.pdf", "page_number": 2},
            ],
            "b": [
                {"id": "b", "coords": (500.0, 600.0), "confidence": 0.70, "source_file": "second.pdf", "page_number": 1},
                {"id": "b", "coords": (700.0, 800.0), "confidence": 0.70, "source_file": "first.pdf", "page_number": 1},
            ],
        }
        merged = apply_locator_candidates(
            question_results=results,
            candidates=candidates,
            pdf_paths=[Path("first.pdf"), Path("second.pdf")],
        )
        by_id = {item.id: item for item in merged}
        self.assertEqual(by_id["a"].coords, (300.0, 400.0))
        self.assertEqual(by_id["a"].source_file, "second.pdf")
        self.assertEqual(by_id["a"].page_number, 2)
        self.assertEqual(by_id["b"].coords, (700.0, 800.0))
        self.assertEqual(by_id["b"].source_file, "first.pdf")


if __name__ == "__main__":
    unittest.main()

