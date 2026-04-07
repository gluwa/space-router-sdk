"""Integration tests for the SpaceRouter Python SDK.

These tests hit the **live** Coordination API and proxy gateway at
``gateway.spacerouter.org``.  They require the ``SR_API_KEY`` environment
variable to be set to a billing-provisioned key:

    SR_API_KEY=sr_live_xxx pytest tests/test_integration.py -v
"""

from __future__ import annotations

import os

import pytest

from spacerouter import SpaceRouterAdmin, SpaceRouter


COORDINATION_URL = os.environ.get(
    "SR_COORDINATION_API_URL", "https://coordination.spacerouter.org"
)
GATEWAY_URL = os.environ.get(
    "SR_GATEWAY_URL", "https://gateway.spacerouter.org"
)

# A billing-provisioned API key for proxy tests.
API_KEY = os.environ.get("SR_API_KEY")

pytestmark = pytest.mark.skipif(not API_KEY, reason="SR_API_KEY not set")


class TestIntegration:
    """End-to-end tests against the live Space Router infrastructure."""

    def test_proxy_request(self):
        """Proxy a request through the gateway with a billing-provisioned key."""
        with SpaceRouter(API_KEY, gateway_url=GATEWAY_URL) as client:
            resp = client.get("https://httpbin.org/ip")
            assert resp.status_code == 200

            body = resp.json()
            assert "origin" in body

    def test_api_key_crud(self):
        """Create, list, and revoke an API key."""
        with SpaceRouterAdmin(COORDINATION_URL) as admin:
            key = admin.create_api_key("integration-crud-py")
            key_id = key.id

            try:
                keys = admin.list_api_keys()
                ids = [k.id for k in keys]
                assert key_id in ids
            finally:
                admin.revoke_api_key(key_id)

    def test_node_list(self):
        """List nodes via the admin client."""
        with SpaceRouterAdmin(COORDINATION_URL) as admin:
            nodes = admin.list_nodes()
            assert isinstance(nodes, list)
