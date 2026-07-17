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

    def test_discover_submission_units_skips_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            
            # A student folder with only index.html/htm/txt or hidden files
            student1 = root / "123 - Student One"
            student1.mkdir()
            (student1 / "index.html").write_text("html", encoding="utf-8")
            (student1 / "index.txt").write_text("text", encoding="utf-8")
            (student1 / ".hidden").write_text("hidden", encoding="utf-8")
            
            # A student folder with index.html AND a PDF
            student2 = root / "456 - Student Two"
            student2.mkdir()
            (student2 / "index.html").write_text("html", encoding="utf-8")
            (student2 / "submission.pdf").write_bytes(b"%PDF-1.4")
            
            # A file (not directory) at the root level of submissions
            (root / "index.html").write_text("html", encoding="utf-8")
            
            # A hidden folder at the root level of submissions
            (root / ".hidden_folder").mkdir()
            (root / ".hidden_folder" / "some.pdf").write_bytes(b"%PDF-1.4")
            
            units = discover_submission_units(root)
            
            # Only student2 should be discovered because student1 had no PDF/convertible files (index.html is ignored/skipped).
            # The root index.html should be ignored because it is a file.
            # The hidden folder .hidden_folder should be skipped because it starts with '.'
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0].student_name, "Student Two")
            self.assertEqual(len(units[0].pdf_paths), 1)
            self.assertEqual(units[0].pdf_paths[0].name, "submission.pdf")

if __name__ == "__main__":
    unittest.main()

