from __future__ import annotations

import datetime
import time
import unittest
from unittest.mock import patch, MagicMock

from grader.rate_limit import (
    RateLimiter,
    RateLimiterRegistry,
    DailyLimitExhausted,
    get_pacific_date,
)


class TestRateLimit(unittest.TestCase):
    def test_pacific_date(self) -> None:
        d = get_pacific_date()
        self.assertIsInstance(d, datetime.date)

    def test_rate_limiter_registry_matching(self) -> None:
        registry = RateLimiterRegistry()
        
        # Test specific models
        lim_gemma = registry.get_limiter("gemma4-31b-it")
        self.assertEqual(lim_gemma.rpm, 15)
        self.assertEqual(lim_gemma.rpd, 1500)
        
        lim_flash_lite = registry.get_limiter("gemini-3.1-flash-lite")
        self.assertEqual(lim_flash_lite.rpm, 15)
        self.assertEqual(lim_flash_lite.rpd, 1500)
        
        lim_flash_old = registry.get_limiter("gemini-3-flash")
        self.assertEqual(lim_flash_old.rpm, 5)
        self.assertEqual(lim_flash_old.rpd, 20)
        
        # Test fallback / default
        lim_unknown = registry.get_limiter("unknown-model-xyz")
        self.assertEqual(lim_unknown.rpm, 5)
        self.assertEqual(lim_unknown.rpd, 500)

        # Registry should return same instance for same model
        self.assertIs(registry.get_limiter("gemma4-31b-it"), lim_gemma)

    @patch("time.sleep")
    @patch("time.monotonic")
    def test_sliding_window_rpm(self, mock_monotonic, mock_sleep) -> None:
        # 3 RPM limiter
        lim = RateLimiter("test-model", rpm=3, rpd=10)
        
        # T = 0
        mock_monotonic.return_value = 100.0
        lim.acquire()
        lim.acquire()
        lim.acquire()
        
        # 4th acquire should block and sleep
        # The oldest is at 100.0, so it should sleep 60s
        mock_monotonic.return_value = 100.1
        lim.acquire()
        
        self.assertTrue(mock_sleep.called)
        # Sleep duration should be roughly 60 - (100.1 - 100.0) = 59.9 (plus random jitter)
        sleep_arg = mock_sleep.call_args[0][0]
        self.assertGreaterEqual(sleep_arg, 59.8)
        self.assertLessEqual(sleep_arg, 60.2)

    @patch("grader.rate_limit.get_pacific_date")
    def test_daily_limit_exhausted(self, mock_get_date) -> None:
        mock_get_date.return_value = datetime.date(2026, 7, 8)
        
        # Limiter with 2 requests per day
        lim = RateLimiter("test-model", rpm=10, rpd=2)
        
        lim.acquire()
        lim.acquire()
        
        with self.assertRaises(DailyLimitExhausted):
            lim.acquire()
            
        # If date rolls over, limits reset
        mock_get_date.return_value = datetime.date(2026, 7, 9)
        lim.acquire()  # should succeed
