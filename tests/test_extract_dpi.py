from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from grader.extract import compute_optimal_dpi


class TestExtractDpi(unittest.TestCase):
    @patch("subprocess.run")
    def test_standard_letter_size_uses_default(self, mock_run: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "Page size:      612 x 792 pts (letter)\n"
        mock_run.return_value = mock_result

        dpi = compute_optimal_dpi(Path("dummy.pdf"), target_max_dim=2048.0, default_dpi=150.0)
        self.assertEqual(dpi, 150.0)

    @patch("subprocess.run")
    def test_large_scanned_pdf_scales_down(self, mock_run: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "Page size:      2160 x 3840 pts\n"
        mock_run.return_value = mock_result

        dpi = compute_optimal_dpi(Path("dummy.pdf"), target_max_dim=2048.0, default_dpi=150.0)
        # target_max_dim = 2048.0, max_pts = 3840
        # dpi = 2048.0 * 72.0 / 3840 = 38.4
        self.assertAlmostEqual(dpi, 38.4)

    @patch("subprocess.run")
    def test_invalid_pdfinfo_output_uses_default(self, mock_run: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "Page size: invalid\n"
        mock_run.return_value = mock_result

        dpi = compute_optimal_dpi(Path("dummy.pdf"), target_max_dim=2048.0, default_dpi=150.0)
        self.assertEqual(dpi, 150.0)

    @patch("subprocess.run")
    def test_pdfinfo_failure_uses_default(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "pdfinfo")
        
        dpi = compute_optimal_dpi(Path("dummy.pdf"), target_max_dim=2048.0, default_dpi=150.0)
        self.assertEqual(dpi, 150.0)

if __name__ == "__main__":
    unittest.main()
