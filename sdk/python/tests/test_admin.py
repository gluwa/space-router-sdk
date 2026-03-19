"""Tests for the SpaceRouterAdmin client."""

import httpx
import pytest
import respx

from spacerouter import AsyncSpaceRouterAdmin, SpaceRouterAdmin
from spacerouter.models import (
    ApiKey,
    ApiKeyInfo,
    BillingReissueResult,
    CheckoutSession,
    Node,
    RegisterChallenge,
    RegisterResult,
    TransferPage,
)


# ---------------------------------------------------------------------------
# SpaceRouterAdmin (sync)
# ---------------------------------------------------------------------------


class TestSpaceRouterAdmin:
    @respx.mock
    def test_create_api_key(self):
        respx.post("https://coordination.spacerouter.org/api-keys").mock(
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
        respx.post("https://coordination.spacerouter.org/api-keys").mock(
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
        respx.get("https://coordination.spacerouter.org/api-keys").mock(
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
        respx.delete("https://coordination.spacerouter.org/api-keys/key-uuid").mock(
            return_value=httpx.Response(204)
        )
        with SpaceRouterAdmin() as admin:
            admin.revoke_api_key("key-uuid")  # should not raise

    @respx.mock
    def test_server_error_raises(self):
        respx.post("https://coordination.spacerouter.org/api-keys").mock(
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
# Node management (sync)
# ---------------------------------------------------------------------------

_SAMPLE_NODE = {
    "id": "node-uuid",
    "endpoint_url": "http://192.168.1.100:9090",
    "public_ip": "73.162.1.1",
    "connectivity_type": "direct",
    "node_type": "residential",
    "status": "online",
    "health_score": 1.0,
    "region": "US",
    "label": "my-node",
    "ip_type": "residential",
    "ip_region": "US",
    "as_type": "isp",
    "wallet_address": "0xabc",
    "created_at": "2025-01-01T00:00:00Z",
    "gateway_ca_cert": "CERT",
}


class TestNodeManagement:
    @respx.mock
    def test_register_node(self):
        respx.post("https://coordination.spacerouter.org/nodes").mock(
            return_value=httpx.Response(201, json=_SAMPLE_NODE)
        )
        with SpaceRouterAdmin() as admin:
            node = admin.register_node(
                endpoint_url="http://192.168.1.100:9090",
                wallet_address="0xabc",
                label="my-node",
            )
            assert isinstance(node, Node)
            assert node.id == "node-uuid"
            assert node.status == "online"

    @respx.mock
    def test_list_nodes(self):
        respx.get("https://coordination.spacerouter.org/nodes").mock(
            return_value=httpx.Response(200, json=[_SAMPLE_NODE])
        )
        with SpaceRouterAdmin() as admin:
            nodes = admin.list_nodes()
            assert len(nodes) == 1
            assert isinstance(nodes[0], Node)

    @respx.mock
    def test_update_node_status(self):
        respx.patch("https://coordination.spacerouter.org/nodes/node-1/status").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        with SpaceRouterAdmin() as admin:
            admin.update_node_status("node-1", status="draining")

    @respx.mock
    def test_delete_node(self):
        respx.delete("https://coordination.spacerouter.org/nodes/node-uuid").mock(
            return_value=httpx.Response(204)
        )
        with SpaceRouterAdmin() as admin:
            admin.delete_node("node-uuid")


# ---------------------------------------------------------------------------
# Staking registration (sync)
# ---------------------------------------------------------------------------


class TestStakingRegistration:
    @respx.mock
    def test_get_register_challenge(self):
        respx.post("https://coordination.spacerouter.org/nodes/register/challenge").mock(
            return_value=httpx.Response(200, json={"nonce": "abc123", "expires_in": 300})
        )
        with SpaceRouterAdmin() as admin:
            challenge = admin.get_register_challenge("0xwallet")
            assert isinstance(challenge, RegisterChallenge)
            assert challenge.nonce == "abc123"
            assert challenge.expires_in == 300

    @respx.mock
    def test_verify_and_register(self):
        respx.post("https://coordination.spacerouter.org/nodes/register/verify").mock(
            return_value=httpx.Response(200, json={
                "status": "registered",
                "node_id": "node-new",
                "address": "0xwallet",
                "endpoint_url": "http://node:9090",
                "gateway_ca_cert": "CERT",
            })
        )
        with SpaceRouterAdmin() as admin:
            result = admin.verify_and_register(
                address="0xwallet",
                endpoint_url="http://node:9090",
                signed_nonce="signed-abc",
            )
            assert isinstance(result, RegisterResult)
            assert result.status == "registered"


# ---------------------------------------------------------------------------
# Billing (sync)
# ---------------------------------------------------------------------------


class TestBilling:
    @respx.mock
    def test_create_checkout(self):
        respx.post("https://coordination.spacerouter.org/billing/checkout").mock(
            return_value=httpx.Response(200, json={"checkout_url": "https://checkout.stripe.com/s"})
        )
        with SpaceRouterAdmin() as admin:
            session = admin.create_checkout("user@example.com")
            assert isinstance(session, CheckoutSession)
            assert "stripe.com" in session.checkout_url

    @respx.mock
    def test_verify_email(self):
        respx.get("https://coordination.spacerouter.org/billing/verify").mock(
            return_value=httpx.Response(200)
        )
        with SpaceRouterAdmin() as admin:
            admin.verify_email("token-123")  # should not raise

    @respx.mock
    def test_reissue_api_key(self):
        respx.post("https://coordination.spacerouter.org/billing/reissue").mock(
            return_value=httpx.Response(200, json={"new_api_key": "sr_live_new"})
        )
        with SpaceRouterAdmin() as admin:
            result = admin.reissue_api_key(email="user@example.com", token="tok")
            assert isinstance(result, BillingReissueResult)
            assert result.new_api_key == "sr_live_new"


# ---------------------------------------------------------------------------
# Dashboard (sync)
# ---------------------------------------------------------------------------


class TestDashboard:
    @respx.mock
    def test_get_transfers(self):
        respx.get("https://coordination.spacerouter.org/dashboard/transfers").mock(
            return_value=httpx.Response(200, json={
                "page": 1,
                "total_pages": 5,
                "total_bytes": 1024000,
                "transfers": [{
                    "request_id": "req-1",
                    "bytes": 512,
                    "method": "GET",
                    "target_host": "example.com",
                    "created_at": "2025-01-01T00:00:00Z",
                }],
            })
        )
        with SpaceRouterAdmin() as admin:
            result = admin.get_transfers(wallet_address="0xabc", page=1, page_size=10)
            assert isinstance(result, TransferPage)
            assert result.total_pages == 5
            assert len(result.transfers) == 1


# ---------------------------------------------------------------------------
# AsyncSpaceRouterAdmin
# ---------------------------------------------------------------------------


class TestAsyncSpaceRouterAdmin:
    @pytest.mark.asyncio
    @respx.mock
    async def test_create_api_key(self):
        respx.post("https://coordination.spacerouter.org/api-keys").mock(
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
        respx.get("https://coordination.spacerouter.org/api-keys").mock(
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
        respx.delete("https://coordination.spacerouter.org/api-keys/uuid-1").mock(
            return_value=httpx.Response(204)
        )
        async with AsyncSpaceRouterAdmin() as admin:
            await admin.revoke_api_key("uuid-1")

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with AsyncSpaceRouterAdmin() as admin:
            assert isinstance(admin, AsyncSpaceRouterAdmin)


# ---------------------------------------------------------------------------
# Async node management
# ---------------------------------------------------------------------------


class TestAsyncNodeManagement:
    @pytest.mark.asyncio
    @respx.mock
    async def test_register_node(self):
        respx.post("https://coordination.spacerouter.org/nodes").mock(
            return_value=httpx.Response(201, json=_SAMPLE_NODE)
        )
        async with AsyncSpaceRouterAdmin() as admin:
            node = await admin.register_node(
                endpoint_url="http://192.168.1.100:9090",
                wallet_address="0xabc",
            )
            assert isinstance(node, Node)

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_nodes(self):
        respx.get("https://coordination.spacerouter.org/nodes").mock(
            return_value=httpx.Response(200, json=[_SAMPLE_NODE])
        )
        async with AsyncSpaceRouterAdmin() as admin:
            nodes = await admin.list_nodes()
            assert len(nodes) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_register_challenge(self):
        respx.post("https://coordination.spacerouter.org/nodes/register/challenge").mock(
            return_value=httpx.Response(200, json={"nonce": "abc", "expires_in": 300})
        )
        async with AsyncSpaceRouterAdmin() as admin:
            challenge = await admin.get_register_challenge("0xwallet")
            assert challenge.nonce == "abc"

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_checkout(self):
        respx.post("https://coordination.spacerouter.org/billing/checkout").mock(
            return_value=httpx.Response(200, json={"checkout_url": "https://stripe.com/s"})
        )
        async with AsyncSpaceRouterAdmin() as admin:
            session = await admin.create_checkout("user@test.com")
            assert isinstance(session, CheckoutSession)

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_transfers(self):
        respx.get("https://coordination.spacerouter.org/dashboard/transfers").mock(
            return_value=httpx.Response(200, json={
                "page": 1, "total_pages": 1, "total_bytes": 0, "transfers": [],
            })
        )
        async with AsyncSpaceRouterAdmin() as admin:
            result = await admin.get_transfers(wallet_address="0x1")
            assert isinstance(result, TransferPage)
