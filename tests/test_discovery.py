from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grader.discovery import discover_submission_units, parse_folder_name


class DiscoveryTests(unittest.TestCase):
    def test_parse_folder_name(self) -> None:
        token, name = parse_folder_name("123-456 - Jane Doe - Feb 24, 2026 851 AM")
        self.assertEqual(token, "123-456")
        self.assertEqual(name, "Jane Doe")

    def test_discover_submission_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            student = root / "123-456 - Jane Doe - Feb 24, 2026 851 AM"
            student.mkdir()
            (student / "file1.pdf").write_bytes(b"%PDF-1.4")
            (student / "nested").mkdir()
            (student / "nested" / "file2.pdf").write_bytes(b"%PDF-1.4")
            (root / "no_pdfs").mkdir()

            units = discover_submission_units(root)
            self.assertEqual(len(units), 1)
            unit = units[0]
            self.assertEqual(unit.folder_token, "123-456")
            self.assertEqual(unit.student_name, "Jane Doe")
            self.assertEqual(len(unit.pdf_paths), 2)
            self.assertEqual(unit.pdf_paths[0].name, "file1.pdf")


if __name__ == "__main__":
    unittest.main()

