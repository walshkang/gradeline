from __future__ import annotations

import unittest
from pathlib import Path

from grader.extract import png_output_path, sanitize_for_filename


class ExtractPathTests(unittest.TestCase):
    def test_sanitize_for_filename_handles_trailing_dot(self) -> None:
        self.assertEqual(sanitize_for_filename("Ben Weinster."), "Ben_Weinster")
        self.assertEqual(sanitize_for_filename("..."), "document")

    def test_png_output_path_preserves_unique_suffix(self) -> None:
        prefix = Path(".grader_tmp/Ben_Weinster_1_abcd1234")
        self.assertEqual(str(png_output_path(prefix)), ".grader_tmp/Ben_Weinster_1_abcd1234.png")


if __name__ == "__main__":
    unittest.main()

