"""Integration tests for the SpaceRouter Python SDK (LEGACY — v1.4 API-key flow).

DEPRECATED 2026-04-27. The v1.4 ``sr_live_*`` API-key flow is dead on the
test gateway after the v1.5 escrow rollout: the gateway no longer
provisions or accepts API keys, so the production-style auth these tests
exercise has no working backend.

This file is kept on disk for historical reference (see git blame for the
v1.4 SDK shape) but every test is skipped at module load. The replacement
is ``test_e2e_testnet.py`` next to this file, which exercises the v1.5
escrow-signed-receipt flow end-to-end.

Constraint from the v1.5 rollout: do NOT delete this file. Promote a new
test module instead so ``git log`` reads as a deprecation, not a rewrite.
"""

from __future__ import annotations

import os

import pytest

from spacerouter import SpaceRouterAdmin, SpaceRouter

# Hard skip the whole module — the API-key flow these tests rely on has
# been retired on the test gateway. See ``test_e2e_testnet.py``.
pytestmark = pytest.mark.skip(
    reason=(
        "v1.4 API-key flow retired post-v1.5 escrow rollout — see "
        "test_e2e_testnet.py for the replacement."
    ),
)


COORDINATION_URL = os.environ.get(
    "SR_COORDINATION_API_URL", "https://coordination.spacerouter.org"
)
GATEWAY_URL = os.environ.get(
    "SR_GATEWAY_URL", "https://gateway.spacerouter.org"
)

# A billing-provisioned API key for proxy tests. Retained for historical
# reference; the gateway rejects ``sr_live_*`` keys post-v1.5.
API_KEY = os.environ.get("SR_API_KEY")


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
