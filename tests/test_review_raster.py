from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from grader.review.raster import RasterImageCache, parse_scale


def make_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "hello")
        doc.save(path)
    finally:
        doc.close()


class ReviewRasterTests(unittest.TestCase):
    def test_cache_returns_same_etag_for_repeated_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "doc.pdf"
            make_pdf(pdf)
            cache = RasterImageCache(max_entries=8)

            first = cache.get_page_image(
                submission_id="s1",
                pdf_path=pdf,
                doc_idx=0,
                page_idx=0,
                scale=1.2,
            )
            second = cache.get_page_image(
                submission_id="s1",
                pdf_path=pdf,
                doc_idx=0,
                page_idx=0,
                scale=1.2,
            )

            self.assertEqual(first.meta.etag, second.meta.etag)
            self.assertEqual(first.png_bytes, second.png_bytes)
            self.assertGreater(first.meta.image_width_px, 0)
            self.assertGreater(first.meta.image_height_px, 0)

    def test_parse_scale_clamps_and_defaults(self) -> None:
        self.assertEqual(parse_scale(None), 1.2)
        self.assertEqual(parse_scale(""), 1.2)
        self.assertEqual(parse_scale("0.1"), 0.5)
        self.assertEqual(parse_scale("5"), 3.0)
        self.assertEqual(parse_scale("1.7"), 1.7)


if __name__ == "__main__":
    unittest.main()
