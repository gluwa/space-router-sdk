"""Tests for Tailscale IP detection and setup."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.tailscale import _detect_via_cli, detect_tailscale_ip, ensure_tailscale_up


class TestDetectViaCli:
    @pytest.mark.asyncio
    async def test_success(self):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"100.64.1.5\n", b""))
        proc.returncode = 0

        with patch("app.tailscale.asyncio.create_subprocess_exec", return_value=proc):
            ip = await _detect_via_cli()

        assert ip == "100.64.1.5"

    @pytest.mark.asyncio
    async def test_cli_not_found(self):
        with patch(
            "app.tailscale.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError,
        ):
            ip = await _detect_via_cli()

        assert ip is None

    @pytest.mark.asyncio
    async def test_cli_not_connected(self):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b"Tailscale is stopped\n"))
        proc.returncode = 1

        with patch("app.tailscale.asyncio.create_subprocess_exec", return_value=proc):
            ip = await _detect_via_cli()

        assert ip is None

    @pytest.mark.asyncio
    async def test_cli_timeout(self):
        with patch(
            "app.tailscale.asyncio.create_subprocess_exec",
            side_effect=asyncio.TimeoutError,
        ):
            ip = await _detect_via_cli()

        assert ip is None


class TestDetectTailscaleIp:
    @pytest.mark.asyncio
    async def test_returns_none_when_unavailable(self):
        """Both local API and CLI fail — returns None."""
        with (
            patch("app.tailscale._detect_via_local_api", return_value=None),
            patch("app.tailscale._detect_via_cli", return_value=None),
        ):
            ip = await detect_tailscale_ip()

        assert ip is None

    @pytest.mark.asyncio
    async def test_prefers_local_api(self):
        with (
            patch("app.tailscale._detect_via_local_api", return_value="100.64.1.10"),
            patch("app.tailscale._detect_via_cli", return_value="100.64.1.99"),
        ):
            ip = await detect_tailscale_ip()

        assert ip == "100.64.1.10"

    @pytest.mark.asyncio
    async def test_falls_back_to_cli(self):
        with (
            patch("app.tailscale._detect_via_local_api", return_value=None),
            patch("app.tailscale._detect_via_cli", return_value="100.64.1.20"),
        ):
            ip = await detect_tailscale_ip()

        assert ip == "100.64.1.20"


class TestEnsureTailscaleUp:
    @pytest.mark.asyncio
    async def test_already_connected(self):
        with patch("app.tailscale.detect_tailscale_ip", return_value="100.64.1.5"):
            result = await ensure_tailscale_up("tskey-auth-xxx")

        assert result is True

    @pytest.mark.asyncio
    async def test_no_auth_key_and_not_connected(self):
        with patch("app.tailscale.detect_tailscale_ip", return_value=None):
            result = await ensure_tailscale_up("")

        assert result is False

    @pytest.mark.asyncio
    async def test_brings_up_successfully(self):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0

        call_count = 0

        async def detect_side_effect():
            nonlocal call_count
            call_count += 1
            # First call: not connected; second call: connected
            return None if call_count == 1 else "100.64.1.5"

        with (
            patch("app.tailscale.detect_tailscale_ip", side_effect=detect_side_effect),
            patch("app.tailscale.asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await ensure_tailscale_up("tskey-auth-xxx")

        assert result is True

    @pytest.mark.asyncio
    async def test_tailscale_up_fails(self):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b"error\n"))
        proc.returncode = 1

        with (
            patch("app.tailscale.detect_tailscale_ip", return_value=None),
            patch("app.tailscale.asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await ensure_tailscale_up("tskey-auth-xxx")

        assert result is False
