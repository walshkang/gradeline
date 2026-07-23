from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from grader.workflow.audit_pdf import audit_pdf_outputs


class TestAuditPDF(unittest.TestCase):
    def test_directory_not_found(self) -> None:
        non_existent = Path("/tmp/non_existent_directory_gradeline_test")
        result = audit_pdf_outputs(non_existent)
        self.assertIn("error", result)

    def test_clean_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            pdf_path = out_dir / "clean_student.pdf"
            doc = fitz.open()
            page = doc.new_page(width=612, height=792)

            # Add two normal annotations separated vertically below top margin
            rect1 = fitz.Rect(50, 200, 150, 240)
            annot1 = page.add_freetext_annot(rect1, "Q1: 10/10")
            annot1.set_info(subject="question_mark|q=1")

            rect2 = fitz.Rect(50, 350, 150, 390)
            annot2 = page.add_freetext_annot(rect2, "Q2: 10/10")
            annot2.set_info(subject="question_mark|q=2")

            doc.save(str(pdf_path))
            doc.close()

            results = audit_pdf_outputs(out_dir)
            self.assertEqual(results["total_pdfs"], 1)
            self.assertEqual(results["oob_defects"], 0)
            self.assertEqual(results["overlap_defects"], 0)
            self.assertEqual(results["page_mismatches"], 0)
            self.assertEqual(results["top_margin_clustering"], 0)
            self.assertEqual(results["oversized_anchor_boxes"], 0)
            self.assertEqual(results["same_y_clustering"], 0)

    def test_top_margin_clustering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            pdf_path = out_dir / "top_margin_student.pdf"
            doc = fitz.open()
            page = doc.new_page(width=612, height=792)

            # Top margin is < 792 * 0.15 = 118.8
            # Add 3 annotations in top margin
            for i in range(3):
                rect = fitz.Rect(50 + i * 60, 20, 100 + i * 60, 50)
                annot = page.add_freetext_annot(rect, f"Q{i+1}")
                annot.set_info(subject=f"question_mark|q={i+1}")

            doc.save(str(pdf_path))
            doc.close()

            results = audit_pdf_outputs(out_dir)
            self.assertEqual(results["top_margin_clustering"], 1)

    def test_oversized_anchor_box(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            pdf_path = out_dir / "oversized_student.pdf"
            doc = fitz.open()
            page = doc.new_page(width=612, height=792)

            # Bounding box width > 300
            rect1 = fitz.Rect(50, 200, 400, 230)
            annot1 = page.add_freetext_annot(rect1, "Oversized Width")
            annot1.set_info(subject="question_mark|q=1")

            # Bounding box height > 80
            rect2 = fitz.Rect(50, 300, 150, 400)
            annot2 = page.add_freetext_annot(rect2, "Oversized Height")
            annot2.set_info(subject="question_mark|q=2")

            doc.save(str(pdf_path))
            doc.close()

            results = audit_pdf_outputs(out_dir)
            self.assertEqual(results["oversized_anchor_boxes"], 2)

    def test_same_y_clustering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            pdf_path = out_dir / "same_y_student.pdf"
            doc = fitz.open()
            page = doc.new_page(width=612, height=792)

            # 3 annotations with y0 within +-5pt (y0 = 250.0, 252.0, 254.0)
            y_base = 250.0
            for i in range(3):
                rect = fitz.Rect(50 + i * 80, y_base + i * 2, 120 + i * 80, y_base + i * 2 + 30)
                annot = page.add_freetext_annot(rect, f"Q{i+1}")
                annot.set_info(subject=f"question_mark|q={i+1}")

            doc.save(str(pdf_path))
            doc.close()

            results = audit_pdf_outputs(out_dir)
            self.assertEqual(results["same_y_clustering"], 1)


if __name__ == "__main__":
    unittest.main()
