import base64

import httpx
import pytest
import respx

from app.auth import AuthResult, AuthValidator, extract_api_key, hash_api_key
from app.errors import AuthenticationError


class TestExtractApiKey:
    def test_valid_basic_auth(self):
        encoded = base64.b64encode(b"sr_live_abc123:").decode()
        header = f"Basic {encoded}"
        assert extract_api_key(header) == "sr_live_abc123"

    def test_valid_basic_auth_lowercase(self):
        encoded = base64.b64encode(b"sr_live_abc123:").decode()
        header = f"basic {encoded}"
        assert extract_api_key(header) == "sr_live_abc123"

    def test_missing_header(self):
        with pytest.raises(AuthenticationError):
            extract_api_key(None)

    def test_malformed_not_basic(self):
        with pytest.raises(AuthenticationError):
            extract_api_key("Bearer token123")

    def test_malformed_bad_base64(self):
        with pytest.raises(AuthenticationError):
            extract_api_key("Basic !!!not-base64!!!")

    def test_empty_key(self):
        encoded = base64.b64encode(b":password").decode()
        with pytest.raises(AuthenticationError):
            extract_api_key(f"Basic {encoded}")

    def test_key_with_password_part(self):
        encoded = base64.b64encode(b"sr_live_abc123:ignored").decode()
        header = f"Basic {encoded}"
        assert extract_api_key(header) == "sr_live_abc123"


class TestHashApiKey:
    def test_consistent_hash(self):
        h1 = hash_api_key("sr_live_abc123")
        h2 = hash_api_key("sr_live_abc123")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_keys_different_hashes(self):
        assert hash_api_key("key1") != hash_api_key("key2")


class TestAuthValidator:
    @pytest.mark.asyncio
    async def test_validate_success(self, settings, mock_api):
        mock_api.post("http://coordination.test/internal/auth/validate").respond(
            200,
            json={"valid": True, "api_key_id": "uuid-123", "rate_limit_rpm": 100},
        )

        async with httpx.AsyncClient() as client:
            validator = AuthValidator(client, settings)
            result = await validator.validate("sr_live_abc123")

        assert result.valid is True
        assert result.api_key_id == "uuid-123"
        assert result.rate_limit_rpm == 100

    @pytest.mark.asyncio
    async def test_validate_invalid_key(self, settings, mock_api):
        mock_api.post("http://coordination.test/internal/auth/validate").respond(
            200,
            json={"valid": False},
        )

        async with httpx.AsyncClient() as client:
            validator = AuthValidator(client, settings)
            result = await validator.validate("sr_live_bad_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_validate_caches_result(self, settings, mock_api):
        route = mock_api.post("http://coordination.test/internal/auth/validate").respond(
            200,
            json={"valid": True, "api_key_id": "uuid-123", "rate_limit_rpm": 60},
        )

        async with httpx.AsyncClient() as client:
            validator = AuthValidator(client, settings)
            r1 = await validator.validate("sr_live_cache_test")
            r2 = await validator.validate("sr_live_cache_test")

        assert r1.valid is True
        assert r2.valid is True
        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_validate_network_error_sqlite_fallback(self, settings, mock_api):
        """In SQLite mode, network errors fall back to local test key."""
        settings.USE_SQLITE = True
        mock_api.post("http://coordination.test/internal/auth/validate").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        async with httpx.AsyncClient() as client:
            validator = AuthValidator(client, settings)
            result = await validator.validate("sr_live_abc123")

        # SQLite mode provides a fallback auth result
        assert result is not None
        assert result.api_key_id == "local-test-key"
