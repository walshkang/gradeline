from __future__ import annotations

import json
import unittest

from grader.streaming import StreamProgressParser


class StreamProgressParserTests(unittest.TestCase):
    def test_detects_question_ids_in_order_from_chunks(self) -> None:
        payload = {
            "student_submission_id": "sub-1",
            "questions": [
                {"id": "a", "logic_analysis": "x", "verdict": "correct"},
                {"id": "b", "logic_analysis": "y", "verdict": "incorrect"},
                {"id": "c", "logic_analysis": "z", "verdict": "partial"},
            ],
            "global_flags": [],
        }
        text = json.dumps(payload, separators=(",", ":"))

        seen: list[tuple[int, str]] = []

        parser = StreamProgressParser(
            on_question=lambda idx, qid: seen.append((idx, qid)),
        )

        # Feed in small, uneven chunks to simulate streaming.
        step = 7
        for i in range(0, len(text), step):
            parser.feed(text[i : i + step])

        self.assertEqual(seen, [(1, "a"), (2, "b"), (3, "c")])
        self.assertEqual(parser.get_buffer(), text)


if __name__ == "__main__":
    unittest.main()

