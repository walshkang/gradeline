from __future__ import annotations

import unittest
from grader.cost import TokenUsage, calculate_cost, extract_token_usage, get_model_rates


class TestCostCalculator(unittest.TestCase):
    def test_calculate_cost_flash(self) -> None:
        usage = calculate_cost(
            model_name="gemini-2.5-flash",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cached_tokens=0,
        )
        self.assertEqual(usage.input_tokens, 1_000_000)
        self.assertEqual(usage.output_tokens, 1_000_000)
        self.assertAlmostEqual(usage.cost_usd, 0.375, places=4)

    def test_calculate_cost_with_caching(self) -> None:
        usage = calculate_cost(
            model_name="gemini-1.5-flash",
            input_tokens=1_000_000,
            output_tokens=500_000,
            cached_tokens=800_000,
        )
        # Uncached input: 200,000 * 0.075 / 1M = 0.015
        # Cached input: 800,000 * 0.01875 / 1M = 0.015
        # Output: 500,000 * 0.30 / 1M = 0.150
        # Total cost: 0.180
        self.assertAlmostEqual(usage.cost_usd, 0.180, places=4)

    def test_token_usage_addition(self) -> None:
        t1 = TokenUsage(input_tokens=100, output_tokens=50, cached_tokens=10, cost_usd=0.01)
        t2 = TokenUsage(input_tokens=200, output_tokens=100, cached_tokens=20, cost_usd=0.02)
        total = t1 + t2
        self.assertEqual(total.input_tokens, 300)
        self.assertEqual(total.output_tokens, 150)
        self.assertEqual(total.cached_tokens, 30)
        self.assertAlmostEqual(total.cost_usd, 0.03, places=4)

    def test_extract_token_usage_obj(self) -> None:
        class DummyUsage:
            prompt_token_count = 1000
            candidates_token_count = 200
            cached_content_token_count = 500

        class DummyResponse:
            usage_metadata = DummyUsage()

        usage = extract_token_usage(DummyResponse(), "gemini-2.5-flash")
        self.assertEqual(usage.input_tokens, 1000)
        self.assertEqual(usage.output_tokens, 200)
        self.assertEqual(usage.cached_tokens, 500)
        self.assertGreater(usage.cost_usd, 0.0)

    def test_extract_token_usage_dict(self) -> None:
        resp = {
            "usage_metadata": {
                "prompt_token_count": 5000,
                "candidates_token_count": 1000,
                "cached_content_token_count": 0,
            }
        }
        usage = extract_token_usage(resp, "gemini-1.5-pro")
        self.assertEqual(usage.input_tokens, 5000)
        self.assertEqual(usage.output_tokens, 1000)
        self.assertGreater(usage.cost_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
