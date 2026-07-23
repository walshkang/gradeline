from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from grader.extract import parse_tsv_blocks, _needs_gemini_fallback
from grader.ocr_gemini import _parse_json_array, _to_text_blocks
from grader.types import TextBlock


TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"

SAMPLE_TSV = "\n".join([
    TSV_HEADER,
    # block 1, two words
    "5\t1\t1\t1\t1\t1\t100\t200\t50\t20\t95.5\tHello",
    "5\t1\t1\t1\t1\t2\t155\t200\t60\t20\t96.0\tWorld",
    # block 2, one word
    "5\t1\t2\t1\t1\t1\t300\t400\t80\t25\t90.0\tFoo",
    # non-word rows (level != 5) — should be ignored
    "1\t1\t0\t0\t0\t0\t0\t0\t612\t792\t-1\t",
    "4\t1\t1\t1\t1\t0\t100\t200\t115\t20\t-1\t",
    # empty text — should be ignored
    "5\t1\t3\t1\t1\t1\t10\t10\t5\t5\t80.0\t",
])


class ParseTsvBlocksTests(unittest.TestCase):
    def test_groups_words_by_block(self) -> None:
        blocks = parse_tsv_blocks(SAMPLE_TSV, page=1, dpi=300.0)
        self.assertEqual(len(blocks), 2)

    def test_block_ids(self) -> None:
        blocks = parse_tsv_blocks(SAMPLE_TSV, page=1, dpi=300.0)
        self.assertEqual(blocks[0].id, "p1_b1")
        self.assertEqual(blocks[1].id, "p1_b2")

    def test_joins_words_with_space(self) -> None:
        blocks = parse_tsv_blocks(SAMPLE_TSV, page=1, dpi=300.0)
        self.assertEqual(blocks[0].text, "Hello World")
        self.assertEqual(blocks[1].text, "Foo")

    def test_bounding_box_spans_all_words(self) -> None:
        blocks = parse_tsv_blocks(SAMPLE_TSV, page=1, dpi=300.0)
        b = blocks[0]
        scale = 72.0 / 300.0
        self.assertAlmostEqual(b.left, 100.0 * scale)
        self.assertAlmostEqual(b.top, 200.0 * scale)
        self.assertAlmostEqual(b.width, 115.0 * scale)   # max(100+50, 155+60) - 100 = 215 - 100
        self.assertAlmostEqual(b.height, 20.0 * scale)

    def test_mean_confidence(self) -> None:
        blocks = parse_tsv_blocks(SAMPLE_TSV, page=1, dpi=300.0)
        self.assertAlmostEqual(blocks[0].confidence, (95.5 + 96.0) / 2)

    def test_source_tag(self) -> None:
        blocks = parse_tsv_blocks(SAMPLE_TSV, page=1, dpi=300.0)
        self.assertEqual(blocks[0].source, "tesseract_tsv")

    def test_page_number_propagated(self) -> None:
        blocks = parse_tsv_blocks(SAMPLE_TSV, page=3, dpi=300.0)
        self.assertEqual(blocks[0].id, "p3_b1")
        self.assertEqual(blocks[0].page, 3)

    def test_empty_tsv_returns_empty(self) -> None:
        self.assertEqual(parse_tsv_blocks("", page=1, dpi=300.0), [])

    def test_header_only_returns_empty(self) -> None:
        self.assertEqual(parse_tsv_blocks(TSV_HEADER, page=1, dpi=300.0), [])

    def test_malformed_row_skipped(self) -> None:
        tsv = TSV_HEADER + "\n5\t1\tnot_an_int\t1\t1\t1\t100\t200\t50\t20\t95.0\tWord"
        blocks = parse_tsv_blocks(tsv, page=1, dpi=300.0)
        self.assertEqual(blocks, [])


class NeedsGeminiFallbackTests(unittest.TestCase):
    def _block(self, conf: float) -> TextBlock:
        return TextBlock(id="p1_b1", text="hello", page=1, left=0, top=0,
                         width=10, height=10, source="tesseract_tsv", confidence=conf)

    def test_empty_blocks_triggers_fallback(self) -> None:
        self.assertTrue(_needs_gemini_fallback([]))

    def test_high_confidence_no_fallback(self) -> None:
        self.assertFalse(_needs_gemini_fallback([self._block(95.0), self._block(96.0)]))

    def test_low_confidence_triggers_fallback(self) -> None:
        self.assertTrue(_needs_gemini_fallback([self._block(30.0), self._block(40.0)]))

    def test_unknown_confidence_no_fallback(self) -> None:
        # confidence=-1 means unavailable; don't trigger fallback spuriously
        self.assertFalse(_needs_gemini_fallback([self._block(-1.0)]))


class ParseJsonArrayTests(unittest.TestCase):
    def test_parses_plain_json(self) -> None:
        raw = '[{"block_num": 1, "text": "Hello", "left": 10, "top": 20, "width": 50, "height": 15}]'
        result = _parse_json_array(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "Hello")

    def test_strips_markdown_fence(self) -> None:
        raw = '```json\n[{"block_num": 1, "text": "Hi", "left": 0, "top": 0, "width": 10, "height": 10}]\n```'
        result = _parse_json_array(raw)
        self.assertEqual(result[0]["text"], "Hi")

    def test_empty_array(self) -> None:
        self.assertEqual(_parse_json_array("[]"), [])

    def test_invalid_json_returns_empty(self) -> None:
        self.assertEqual(_parse_json_array("not json"), [])


class ToTextBlocksTests(unittest.TestCase):
    def test_basic_conversion(self) -> None:
        raw = [{"block_num": 2, "text": "Hello", "left": 10, "top": 20, "width": 50, "height": 15}]
        blocks = _to_text_blocks(raw, page=2, dpi=216.0)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].id, "p2_b2")
        self.assertEqual(blocks[0].text, "Hello")
        self.assertEqual(blocks[0].page, 2)
        self.assertEqual(blocks[0].source, "gemini_flash")
        self.assertEqual(blocks[0].confidence, -1.0)

    def test_skips_empty_text(self) -> None:
        raw = [{"block_num": 1, "text": "  ", "left": 0, "top": 0, "width": 10, "height": 10}]
        self.assertEqual(_to_text_blocks(raw, page=1, dpi=216.0), [])

    def test_missing_fields_default_to_zero(self) -> None:
        raw = [{"text": "Hi"}]
        blocks = _to_text_blocks(raw, page=1, dpi=216.0)
        self.assertEqual(blocks[0].left, 0.0)
        self.assertEqual(blocks[0].top, 0.0)


class ForceVisionExtractionTests(unittest.TestCase):
    @patch("grader.extract.run_pdftotext", return_value="short")
    @patch("grader.extract.run_ocr_all_pages")
    @patch("grader.extract._run_gemini_fallback")
    def test_force_vision_true_bypasses_tesseract(self, mock_fallback, mock_ocr, mock_pdftext) -> None:
        from grader.extract import extract_pdf_text
        mock_fallback.return_value = [
            TextBlock(id="p1_b1", text="Vision Result", page=1, left=0, top=0, width=10, height=10, source="gemini_flash")
        ]

        result = extract_pdf_text(
            pdf_path=Path("/fake/file.pdf"),
            temp_dir=Path("/fake/tmp"),
            ocr_char_threshold=200,
            gemini_api_key="fake-key",
            force_vision=True,
        )

        mock_ocr.assert_not_called()
        mock_fallback.assert_called_once()
        self.assertEqual(result.source, "gemini_flash")
        self.assertEqual(result.text, "Vision Result")

    @patch("grader.extract.run_pdftotext", return_value="short")
    @patch("grader.extract.run_ocr_all_pages")
    @patch("grader.extract._run_gemini_fallback")
    def test_force_vision_false_uses_tesseract(self, mock_fallback, mock_ocr, mock_pdftext) -> None:
        from grader.extract import extract_pdf_text
        mock_ocr.return_value = [
            TextBlock(id="p1_b1", text="Tesseract Result", page=1, left=0, top=0, width=10, height=10, source="tesseract_tsv", confidence=90.0)
        ]

        result = extract_pdf_text(
            pdf_path=Path("/fake/file.pdf"),
            temp_dir=Path("/fake/tmp"),
            ocr_char_threshold=200,
            gemini_api_key="fake-key",
            force_vision=False,
        )

        mock_ocr.assert_called_once()
        mock_fallback.assert_not_called()
        self.assertEqual(result.source, "ocr")
        self.assertEqual(result.text, "Tesseract Result")

    @patch("grader.extract.run_pdftotext", return_value="A" * 300)
    @patch("grader.extract.run_ocr_all_pages")
    @patch("grader.extract._run_gemini_fallback")
    def test_force_vision_with_rich_native_text_uses_pdftotext(self, mock_fallback, mock_ocr, mock_pdftext) -> None:
        from grader.extract import extract_pdf_text
        result = extract_pdf_text(
            pdf_path=Path("/fake/file.pdf"),
            temp_dir=Path("/fake/tmp"),
            ocr_char_threshold=200,
            gemini_api_key="fake-key",
            force_vision=True,
        )

        mock_ocr.assert_not_called()
        mock_fallback.assert_not_called()
        self.assertEqual(result.source, "pdftotext")


if __name__ == "__main__":
    unittest.main()

