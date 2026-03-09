"""Tests for the SpaceRouterAdmin client."""

import httpx
import pytest
import respx

from spacerouter import AsyncSpaceRouterAdmin, SpaceRouterAdmin
from spacerouter.models import ApiKey, ApiKeyInfo


# ---------------------------------------------------------------------------
# SpaceRouterAdmin (sync)
# ---------------------------------------------------------------------------


class TestSpaceRouterAdmin:
    @respx.mock
    def test_create_api_key(self):
        respx.post("http://localhost:8000/api-keys").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "key-uuid",
                    "name": "my-agent",
                    "api_key": "sr_live_abc123def456",
                    "rate_limit_rpm": 60,
                },
            )
        )
        with SpaceRouterAdmin() as admin:
            key = admin.create_api_key("my-agent")
            assert isinstance(key, ApiKey)
            assert key.id == "key-uuid"
            assert key.api_key.startswith("sr_live_")
            assert key.rate_limit_rpm == 60

    @respx.mock
    def test_create_api_key_custom_rpm(self):
        respx.post("http://localhost:8000/api-keys").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "key-uuid",
                    "name": "fast-agent",
                    "api_key": "sr_live_xyz",
                    "rate_limit_rpm": 200,
                },
            )
        )
        with SpaceRouterAdmin() as admin:
            key = admin.create_api_key("fast-agent", rate_limit_rpm=200)
            assert key.rate_limit_rpm == 200

    @respx.mock
    def test_list_api_keys(self):
        respx.get("http://localhost:8000/api-keys").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "1",
                        "name": "key-one",
                        "key_prefix": "sr_live_aaa",
                        "rate_limit_rpm": 60,
                        "is_active": True,
                        "created_at": "2025-01-01T00:00:00Z",
                    },
                    {
                        "id": "2",
                        "name": "key-two",
                        "key_prefix": "sr_live_bbb",
                        "rate_limit_rpm": 120,
                        "is_active": False,
                        "created_at": "2025-01-02T00:00:00Z",
                    },
                ],
            )
        )
        with SpaceRouterAdmin() as admin:
            keys = admin.list_api_keys()
            assert len(keys) == 2
            assert all(isinstance(k, ApiKeyInfo) for k in keys)
            assert keys[0].is_active is True
            assert keys[1].is_active is False

    @respx.mock
    def test_revoke_api_key(self):
        respx.delete("http://localhost:8000/api-keys/key-uuid").mock(
            return_value=httpx.Response(204)
        )
        with SpaceRouterAdmin() as admin:
            admin.revoke_api_key("key-uuid")  # should not raise

    @respx.mock
    def test_server_error_raises(self):
        respx.post("http://localhost:8000/api-keys").mock(
            return_value=httpx.Response(500, json={"detail": "Internal error"})
        )
        with SpaceRouterAdmin() as admin:
            with pytest.raises(httpx.HTTPStatusError):
                admin.create_api_key("bad")

    def test_custom_base_url(self):
        admin = SpaceRouterAdmin("http://api.example.com:9000")
        assert admin._client.base_url == httpx.URL("http://api.example.com:9000")
        admin.close()

    def test_context_manager(self):
        with SpaceRouterAdmin() as admin:
            assert isinstance(admin, SpaceRouterAdmin)


# ---------------------------------------------------------------------------
# AsyncSpaceRouterAdmin
# ---------------------------------------------------------------------------


class TestAsyncSpaceRouterAdmin:
    @pytest.mark.asyncio
    @respx.mock
    async def test_create_api_key(self):
        respx.post("http://localhost:8000/api-keys").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "key-uuid",
                    "name": "my-agent",
                    "api_key": "sr_live_abc123",
                    "rate_limit_rpm": 60,
                },
            )
        )
        async with AsyncSpaceRouterAdmin() as admin:
            key = await admin.create_api_key("my-agent")
            assert isinstance(key, ApiKey)

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_api_keys(self):
        respx.get("http://localhost:8000/api-keys").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "1",
                        "name": "k",
                        "key_prefix": "sr_live_aaa",
                        "rate_limit_rpm": 60,
                        "is_active": True,
                        "created_at": "2025-01-01T00:00:00Z",
                    },
                ],
            )
        )
        async with AsyncSpaceRouterAdmin() as admin:
            keys = await admin.list_api_keys()
            assert len(keys) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_revoke_api_key(self):
        respx.delete("http://localhost:8000/api-keys/uuid-1").mock(
            return_value=httpx.Response(204)
        )
        async with AsyncSpaceRouterAdmin() as admin:
            await admin.revoke_api_key("uuid-1")

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with AsyncSpaceRouterAdmin() as admin:
            assert isinstance(admin, AsyncSpaceRouterAdmin)
