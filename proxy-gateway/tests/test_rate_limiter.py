import asyncio
import time
from unittest.mock import patch

import pytest

from app.rate_limiter import RateLimiter


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_under_limit(self):
        limiter = RateLimiter()
        for _ in range(60):
            allowed, retry_after = await limiter.check("key1", 60)
            assert allowed is True
            assert retry_after == 0

    @pytest.mark.asyncio
    async def test_blocks_over_limit(self):
        limiter = RateLimiter()
        for _ in range(60):
            await limiter.check("key1", 60)

        allowed, retry_after = await limiter.check("key1", 60)
        assert allowed is False
        assert retry_after > 0

    @pytest.mark.asyncio
    async def test_independent_keys(self):
        limiter = RateLimiter()
        for _ in range(60):
            await limiter.check("key1", 60)

        # key2 should still be allowed
        allowed, _ = await limiter.check("key2", 60)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_window_slides(self):
        limiter = RateLimiter()
        base = time.monotonic()

        # Fill up the window at time=base
        with patch("app.rate_limiter.time.monotonic", return_value=base):
            for _ in range(5):
                await limiter.check("key1", 5)

        # Should be blocked at time=base+30
        with patch("app.rate_limiter.time.monotonic", return_value=base + 30):
            allowed, _ = await limiter.check("key1", 5)
            assert allowed is False

        # Should be allowed at time=base+61 (window expired)
        with patch("app.rate_limiter.time.monotonic", return_value=base + 61):
            allowed, _ = await limiter.check("key1", 5)
            assert allowed is True

    @pytest.mark.asyncio
    async def test_retry_after_calculation(self):
        limiter = RateLimiter()
        base = time.monotonic()

        with patch("app.rate_limiter.time.monotonic", return_value=base):
            for _ in range(5):
                await limiter.check("key1", 5)

        # At base+30, oldest entry is at base, so retry_after = 60 - 30 = 30
        with patch("app.rate_limiter.time.monotonic", return_value=base + 30):
            allowed, retry_after = await limiter.check("key1", 5)
            assert allowed is False
            assert retry_after == 30

    @pytest.mark.asyncio
    async def test_custom_rpm_limit(self):
        limiter = RateLimiter()
        for _ in range(10):
            await limiter.check("key1", 10)

        allowed, _ = await limiter.check("key1", 10)
        assert allowed is False

        # But a different key with higher limit is fine
        allowed, _ = await limiter.check("key1", 100)
        assert allowed is True
