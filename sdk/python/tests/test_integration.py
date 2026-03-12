"""Integration tests for the SpaceRouter Python SDK.

These tests hit the **live** Coordination API and proxy gateway at
``gateway.spacerouter.org``.  They are gated behind the ``SR_INTEGRATION``
environment variable so they never run in normal CI:

    SR_INTEGRATION=1 pytest tests/test_integration.py -v
"""

from __future__ import annotations

import os

import pytest

_RUN = os.environ.get("SR_INTEGRATION", "") == "1"
pytestmark = pytest.mark.skipif(not _RUN, reason="SR_INTEGRATION not set")

from spacerouter import SpaceRouterAdmin, SpaceRouter  # noqa: E402


COORDINATION_URL = os.environ.get(
    "SR_COORDINATION_API_URL", "https://coordination.spacerouter.org"
)
GATEWAY_URL = os.environ.get(
    "SR_GATEWAY_URL", "http://gateway.spacerouter.org:8080"
)


class TestIntegration:
    """End-to-end: create key -> proxy request -> verify headers -> revoke."""

    def test_full_lifecycle(self):
        # 1. Create an ephemeral API key via the Coordination API.
        with SpaceRouterAdmin(COORDINATION_URL) as admin:
            key = admin.create_api_key("integration-test-py")
            assert key.api_key.startswith("sr_live_")
            key_id = key.id

            try:
                # 2. Proxy a request through the gateway.
                with SpaceRouter(key.api_key, gateway_url=GATEWAY_URL) as client:
                    resp = client.get("https://httpbin.org/ip")
                    assert resp.status_code == 200

                    body = resp.json()
                    assert "origin" in body

                    # 3. Verify SpaceRouter headers are present.
                    assert resp.request_id is not None

            finally:
                # 4. Cleanup: revoke the key.
                admin.revoke_api_key(key_id)

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
