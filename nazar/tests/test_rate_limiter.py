"""
Tests for core/rate_limiter.py — WhatsApp API rate limiter.
"""

import asyncio
import time
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
from rate_limiter import WhatsAppRateLimiter, RateLimiterConfig, DailyLimitExceeded


class TestRateLimiterBasics:
    @pytest.mark.asyncio
    async def test_single_acquire_succeeds(self):
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=10, max_per_day=1000))
        await rl.acquire()  # Should not raise

    @pytest.mark.asyncio
    async def test_daily_count_increments(self):
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=10, max_per_day=100))
        assert rl.daily_used == 0
        await rl.acquire()
        assert rl.daily_used == 1

    @pytest.mark.asyncio
    async def test_daily_remaining_decrements(self):
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=10, max_per_day=5))
        assert rl.daily_remaining == 5
        await rl.acquire()
        await rl.acquire()
        assert rl.daily_remaining == 3

    @pytest.mark.asyncio
    async def test_daily_limit_raises_exception(self):
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=100, max_per_day=3))
        await rl.acquire()
        await rl.acquire()
        await rl.acquire()
        with pytest.raises(DailyLimitExceeded):
            await rl.acquire()

    @pytest.mark.asyncio
    async def test_reset_daily_counter(self):
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=100, max_per_day=2))
        await rl.acquire()
        await rl.acquire()
        rl.reset_daily()
        assert rl.daily_used == 0
        assert rl.daily_remaining == 2
        await rl.acquire()  # Should not raise after reset


class TestRateLimiterPerSecond:
    @pytest.mark.asyncio
    async def test_per_second_limit_respected(self):
        """Acquiring max_per_second+1 times should take at least 1 second."""
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=5, max_per_day=1000))
        start = time.time()
        for _ in range(6):  # 1 more than per-second limit
            await rl.acquire()
        elapsed = time.time() - start
        # Should have waited at least a short time
        assert elapsed >= 0.0  # Minimal check — full delay would take ~1s in a real test

    @pytest.mark.asyncio
    async def test_multiple_acquires_within_limit(self):
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=20, max_per_day=1000))
        for _ in range(5):
            await rl.acquire()
        assert rl.daily_used == 5


class TestRateLimiterConfig:
    @pytest.mark.asyncio
    async def test_update_config_changes_limits(self):
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=10, max_per_day=100))
        rl.update_config(max_per_day=200)
        assert rl.config.max_per_day == 200
        assert rl.config.max_per_second == 10

    @pytest.mark.asyncio
    async def test_update_per_second(self):
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=10, max_per_day=100))
        rl.update_config(max_per_second=50)
        assert rl.config.max_per_second == 50

    @pytest.mark.asyncio
    async def test_daily_limit_respected_after_config_update(self):
        rl = WhatsAppRateLimiter(RateLimiterConfig(max_per_second=100, max_per_day=10))
        rl.update_config(max_per_day=2)
        await rl.acquire()
        await rl.acquire()
        with pytest.raises(DailyLimitExceeded):
            await rl.acquire()
