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
    CreditLineStatus,
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
    "identity_address": "0xabc",
    "staking_address": "0xdef",
    "collection_address": "0xabc",
    "created_at": "2025-01-01T00:00:00Z",
}

_SAMPLE_NODE_LEGACY = {
    **{k: v for k, v in _SAMPLE_NODE.items() if k not in ("identity_address", "staking_address", "collection_address")},
    "wallet_address": "0xabc",
}


class TestNodeManagement:
    @respx.mock
    def test_register_node_v020(self):
        respx.post("https://coordination.spacerouter.org/nodes").mock(
            return_value=httpx.Response(201, json=_SAMPLE_NODE)
        )
        with SpaceRouterAdmin() as admin:
            node = admin.register_node(
                endpoint_url="http://192.168.1.100:9090",
                identity_address="0xabc",
                staking_address="0xdef",
                collection_address="0xabc",
                vouching_signature="0xsig",
                vouching_timestamp=1234567890,
                label="my-node",
            )
            assert isinstance(node, Node)
            assert node.id == "node-uuid"
            assert node.identity_address == "0xabc"
            assert node.staking_address == "0xdef"
            assert node.wallet_address == "0xabc"  # backward compat

    @respx.mock
    def test_register_node_legacy_compat(self):
        respx.post("https://coordination.spacerouter.org/nodes").mock(
            return_value=httpx.Response(201, json=_SAMPLE_NODE_LEGACY)
        )
        with SpaceRouterAdmin() as admin:
            with pytest.warns(DeprecationWarning, match="wallet_address is deprecated"):
                node = admin.register_node(
                    endpoint_url="http://192.168.1.100:9090",
                    wallet_address="0xabc",
                    label="my-node",
                )
            assert isinstance(node, Node)
            assert node.identity_address == "0xabc"

    @respx.mock
    def test_register_node_with_identity(self):
        respx.post("https://coordination.spacerouter.org/nodes").mock(
            return_value=httpx.Response(201, json=_SAMPLE_NODE)
        )
        from eth_account import Account
        key = Account.create().key.hex()
        with SpaceRouterAdmin() as admin:
            node = admin.register_node_with_identity(
                private_key=key,
                endpoint_url="http://192.168.1.100:9090",
                staking_address="0xdef",
                label="my-node",
            )
            assert isinstance(node, Node)

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
        from eth_account import Account
        key = Account.create().key.hex()
        with SpaceRouterAdmin() as admin:
            admin.update_node_status("node-1", status="draining", private_key=key)

    @respx.mock
    def test_delete_node(self):
        respx.request("DELETE", "https://coordination.spacerouter.org/nodes/node-uuid").mock(
            return_value=httpx.Response(204)
        )
        from eth_account import Account
        key = Account.create().key.hex()
        with SpaceRouterAdmin() as admin:
            admin.delete_node("node-uuid", private_key=key)


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


class TestCreditLine:
    @respx.mock
    def test_get_credit_line(self):
        respx.get("https://coordination.spacerouter.org/credit-lines/0xabc").mock(
            return_value=httpx.Response(200, json={
                "address": "0xabc",
                "credit_limit": 1000.0,
                "used": 250.0,
                "available": 750.0,
                "status": "active",
                "foundation_managed": True,
            })
        )
        with SpaceRouterAdmin() as admin:
            result = admin.get_credit_line("0xabc")
            assert isinstance(result, CreditLineStatus)
            assert result.available == 750.0
            assert result.foundation_managed is True


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
            result = admin.get_transfers(identity_address="0xabc", page=1, page_size=10)
            assert isinstance(result, TransferPage)
            assert result.total_pages == 5
            assert len(result.transfers) == 1

    @respx.mock
    def test_get_transfers_legacy_compat(self):
        respx.get("https://coordination.spacerouter.org/dashboard/transfers").mock(
            return_value=httpx.Response(200, json={
                "page": 1, "total_pages": 1, "total_bytes": 0, "transfers": [],
            })
        )
        with SpaceRouterAdmin() as admin:
            with pytest.warns(DeprecationWarning, match="wallet_address is deprecated"):
                result = admin.get_transfers(wallet_address="0xabc")
            assert isinstance(result, TransferPage)


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
                identity_address="0xabc",
                staking_address="0xdef",
                collection_address="0xabc",
                vouching_signature="0xsig",
                vouching_timestamp=1234567890,
            )
            assert isinstance(node, Node)
            assert node.identity_address == "0xabc"

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
            result = await admin.get_transfers(identity_address="0x1")
            assert isinstance(result, TransferPage)

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_credit_line(self):
        respx.get("https://coordination.spacerouter.org/credit-lines/0x1").mock(
            return_value=httpx.Response(200, json={
                "address": "0x1", "credit_limit": 500.0, "used": 0.0,
                "available": 500.0, "status": "active", "foundation_managed": True,
            })
        )
        async with AsyncSpaceRouterAdmin() as admin:
            result = await admin.get_credit_line("0x1")
            assert isinstance(result, CreditLineStatus)
