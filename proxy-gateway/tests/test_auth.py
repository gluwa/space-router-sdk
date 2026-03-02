import base64

import httpx
import pytest
import respx

from app.auth import AuthResult, AuthValidator, extract_api_key, hash_api_key


class TestExtractApiKey:
    def test_valid_basic_auth(self):
        encoded = base64.b64encode(b"sr_live_abc123:").decode()
        headers = {"Proxy-Authorization": f"Basic {encoded}"}
        assert extract_api_key(headers) == "sr_live_abc123"

    def test_valid_basic_auth_lowercase(self):
        encoded = base64.b64encode(b"sr_live_abc123:").decode()
        headers = {"proxy-authorization": f"Basic {encoded}"}
        assert extract_api_key(headers) == "sr_live_abc123"

    def test_missing_header(self):
        assert extract_api_key({}) is None

    def test_malformed_not_basic(self):
        headers = {"Proxy-Authorization": "Bearer token123"}
        assert extract_api_key(headers) is None

    def test_malformed_bad_base64(self):
        headers = {"Proxy-Authorization": "Basic !!!not-base64!!!"}
        assert extract_api_key(headers) is None

    def test_empty_key(self):
        encoded = base64.b64encode(b":password").decode()
        headers = {"Proxy-Authorization": f"Basic {encoded}"}
        assert extract_api_key(headers) is None

    def test_key_with_password_part(self):
        encoded = base64.b64encode(b"sr_live_abc123:ignored").decode()
        headers = {"Proxy-Authorization": f"Basic {encoded}"}
        assert extract_api_key(headers) == "sr_live_abc123"


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
        mock_api.post("http://coordination.test/internal/auth/validate").respond(401)

        async with httpx.AsyncClient() as client:
            validator = AuthValidator(client, settings)
            result = await validator.validate("sr_live_bad_key")

        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_caches_result(self, settings, mock_api):
        route = mock_api.post("http://coordination.test/internal/auth/validate").respond(
            200,
            json={"valid": True, "api_key_id": "uuid-123", "rate_limit_rpm": 60},
        )

        async with httpx.AsyncClient() as client:
            validator = AuthValidator(client, settings)
            r1 = await validator.validate("sr_live_abc123")
            r2 = await validator.validate("sr_live_abc123")

        assert r1.valid is True
        assert r2.valid is True
        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_validate_network_error(self, settings, mock_api):
        mock_api.post("http://coordination.test/internal/auth/validate").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        async with httpx.AsyncClient() as client:
            validator = AuthValidator(client, settings)
            result = await validator.validate("sr_live_abc123")

        assert result.valid is False
