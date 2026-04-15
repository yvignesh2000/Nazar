"""
Nazar — WhatsApp API Rate Limiter

Sliding-window rate limiter that enforces:
  - Per-second limit  (burst protection)
  - Per-day limit     (WhatsApp tier enforcement)

WhatsApp Business API tiers:
  Tier 1 — 1,000 business-initiated conversations / 24 h
  Tier 2 — 10,000 / 24 h
  Tier 3 — 100,000 / 24 h

The limiter is applied around every outbound API call so campaigns and
individual sends share the same budget.

Usage::

    await wa_rate_limiter.acquire()  # waits if needed, raises on daily limit
    # ... send message ...
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("nazar")


@dataclass
class RateLimiterConfig:
    max_per_second: int = 20
    max_per_day: int = 1_000   # Tier 1 default; override via settings


class DailyLimitExceeded(Exception):
    """Raised when the configured daily WhatsApp message limit is reached."""


class WhatsAppRateLimiter:
    """
    Thread-safe (asyncio) sliding-window rate limiter for WhatsApp API calls.

    Attributes:
        config: Runtime-mutable config (change ``config.max_per_day`` to update
                the tier without restarting the process).
    """

    def __init__(self, config=None):
        # type: (Optional[RateLimiterConfig]) -> None
        self.config = config or RateLimiterConfig()
        self._second_window = deque()  # type: deque
        self._day_count = 0   # type: int
        self._day_reset = time.time() + 86_400  # type: float
        self._lock = None  # type: Optional[asyncio.Lock]   # created lazily

    def _get_lock(self):
        # type: () -> asyncio.Lock
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self):
        # type: () -> None
        """
        Block until a send slot is available.

        Raises:
            DailyLimitExceeded: when the daily quota is exhausted.
        """
        async with self._get_lock():
            now = time.time()

            # Reset daily counter at midnight (relative to process start)
            if now > self._day_reset:
                self._day_count = 0
                self._day_reset = now + 86_400
                logger.info("WhatsApp daily send counter reset")

            # Daily hard cap
            if self._day_count >= self.config.max_per_day:
                raise DailyLimitExceeded(
                    "WhatsApp daily send limit reached (%d). "
                    "Counter resets in %ds." % (
                        self.config.max_per_day,
                        int(self._day_reset - now),
                    )
                )

            # Per-second sliding window
            while True:
                # Remove entries older than 1 second
                cutoff = now - 1.0
                while self._second_window and self._second_window[0] <= cutoff:
                    self._second_window.popleft()

                if len(self._second_window) < self.config.max_per_second:
                    break  # slot available

                # Wait until the oldest entry ages out
                sleep_for = 1.0 - (now - self._second_window[0]) + 0.001
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                now = time.time()

            self._second_window.append(now)
            self._day_count += 1

    @property
    def daily_remaining(self):
        # type: () -> int
        """How many sends remain in today's quota."""
        return max(0, self.config.max_per_day - self._day_count)

    @property
    def daily_used(self):
        # type: () -> int
        return self._day_count

    def reset_daily(self):
        # type: () -> None
        """Manually reset the daily counter (e.g. for tests or manual override)."""
        self._day_count = 0
        self._day_reset = time.time() + 86_400

    def update_config(self, max_per_second=None, max_per_day=None):
        # type: (Optional[int], Optional[int]) -> None
        """Hot-update limits without restarting."""
        if max_per_second is not None:
            self.config.max_per_second = max_per_second
        if max_per_day is not None:
            self.config.max_per_day = max_per_day
        logger.info(
            "Rate limiter updated: %d/s, %d/day",
            self.config.max_per_second,
            self.config.max_per_day,
        )


# Singleton — imported by server.py
wa_rate_limiter = WhatsAppRateLimiter()
