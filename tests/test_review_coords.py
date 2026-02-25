from __future__ import annotations

import unittest

from grader.review.api import coerce_coords_payload
from grader.review.types import normalize_coords


class ReviewCoordsTests(unittest.TestCase):
    def test_normalize_coords_retains_yx_order(self) -> None:
        self.assertEqual(normalize_coords([10, 20]), [10.0, 20.0])
        self.assertEqual(coerce_coords_payload([30, 40]), [30.0, 40.0])

    def test_normalize_coords_clamps(self) -> None:
        self.assertEqual(normalize_coords([-5, 2000]), [0.0, 1000.0])

    def test_invalid_coords_raise(self) -> None:
        with self.assertRaises(ValueError):
            coerce_coords_payload([1, 2, 3])


if __name__ == "__main__":
    unittest.main()
