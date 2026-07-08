from __future__ import annotations

import datetime
import random
import threading
import time
from collections import deque
from typing import Any

FREE_TIER_LIMITS: dict[str, dict[str, int]] = {
    "gemma-4-31b":        {"rpm": 15, "rpd": 1500},
    "gemma4-31b":         {"rpm": 15, "rpd": 1500},
    "gemma-3":            {"rpm": 30, "rpd": 1500},
    "gemini-3-flash":     {"rpm": 5,  "rpd": 20},
    "gemini-3.1-flash":   {"rpm": 15, "rpd": 1500},
    "gemini-2.5-flash":   {"rpm": 10, "rpd": 1500},
    "gemini-2.0-flash":   {"rpm": 10, "rpd": 1500},
}
DEFAULT_LIMITS = {"rpm": 5, "rpd": 500}


class DailyLimitExhausted(Exception):
    """Exception raised when a model's daily request limit is reached."""
    def __init__(self, model: str, used: int, limit: int) -> None:
        self.model = model
        self.used = used
        self.limit = limit
        super().__init__(
            f"Daily API request limit reached for model '{model}': "
            f"used {used}/{limit} requests. Run checkpointed."
        )


def get_pacific_date() -> datetime.date:
    """Return the current date in US Pacific Time (UTC-7 or UTC-8)."""
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    # Average shift to Pacific Time (approx. -7 hours for PDT/PST compromise)
    pacific_now = utc_now - datetime.timedelta(hours=7)
    return pacific_now.date()


class RateLimiter:
    def __init__(self, model: str, rpm: int, rpd: int) -> None:
        self.model = model
        self.rpm = rpm
        self.rpd = rpd
        self._lock = threading.Lock()
        
        # RPM sliding window (timestamps in monotonic time)
        self._window: deque[float] = deque()
        
        # RPD daily limit tracking
        self._current_date = get_pacific_date()
        self._daily_count = 0

    def acquire(self) -> None:
        """Acquires a request slot, blocking if the RPM limit is exceeded.
        
        Raises DailyLimitExhausted if the daily limit (RPD) is reached.
        """
        with self._lock:
            # 1. Enforce Daily Limit (RPD)
            today = get_pacific_date()
            if today != self._current_date:
                self._current_date = today
                self._daily_count = 0

            if self._daily_count >= self.rpd:
                raise DailyLimitExhausted(self.model, self._daily_count, self.rpd)

            # 2. Enforce Sliding Window RPM
            now = time.monotonic()
            # Evict timestamps older than 60 seconds
            while self._window and (now - self._window[0] >= 60.0):
                self._window.popleft()

            if len(self._window) >= self.rpm:
                # Need to wait until the oldest slot is freed
                oldest = self._window[0]
                sleep_time = 60.0 - (now - oldest)
                if sleep_time > 0:
                    # Add a tiny jitter to prevent multiple threads from waking up at the exact same instant
                    sleep_time += random.uniform(0.05, 0.2)
                    time.sleep(sleep_time)

                # Re-evaluate window after sleeping
                now = time.monotonic()
                while self._window and (now - self._window[0] >= 60.0):
                    self._window.popleft()

            # Record request
            self._window.append(time.monotonic())
            self._daily_count += 1


class RateLimiterRegistry:
    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = threading.Lock()

    def get_limiter(self, model: str) -> RateLimiter:
        """Returns the shared RateLimiter for the given model name."""
        with self._lock:
            normalized = model.lower().strip()
            if normalized not in self._limiters:
                # Find matching limits based on substring matching
                rpm = DEFAULT_LIMITS["rpm"]
                rpd = DEFAULT_LIMITS["rpd"]
                for pattern, limits in FREE_TIER_LIMITS.items():
                    if pattern in normalized:
                        rpm = limits["rpm"]
                        rpd = limits["rpd"]
                        break
                
                self._limiters[normalized] = RateLimiter(model, rpm, rpd)
            return self._limiters[normalized]
