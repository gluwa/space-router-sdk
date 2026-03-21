"""Integration tests for the SpaceRouter CLI.

These tests hit the **live** Coordination API and proxy gateway at
``gateway.spacerouter.org``.  They require the ``SR_API_KEY`` environment
variable to be set to a billing-provisioned key:

    SR_API_KEY=sr_live_xxx pytest tests/test_integration.py -v
"""

from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from spacerouter_cli.main import app


runner = CliRunner()

COORDINATION_URL = os.environ.get(
    "SR_COORDINATION_API_URL", "https://coordination.spacerouter.org"
)
GATEWAY_URL = os.environ.get(
    "SR_GATEWAY_URL", "https://gateway.spacerouter.org:8080"
)

# A billing-provisioned API key for proxy tests.
API_KEY = os.environ.get("SR_API_KEY")

pytestmark = pytest.mark.skipif(not API_KEY, reason="SR_API_KEY not set")


class TestCLIIntegration:
    """End-to-end tests against the live Space Router infrastructure."""

    def test_proxy_request(self):
        """Proxy a GET request through the gateway with a billing-provisioned key."""
        cmd = [
            "request", "get", "https://httpbin.org/ip",
            "--api-key", API_KEY,
            "--gateway-url", GATEWAY_URL,
        ]

        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"request failed: {result.output}"
        data = json.loads(result.output)
        assert data["status_code"] == 200
        assert "origin" in data["body"]

    def test_api_key_crud(self):
        """Create, list, and revoke an API key via CLI."""
        # Create
        result = runner.invoke(app, [
            "api-key", "create",
            "--name", "integration-crud-cli",
            "--coordination-url", COORDINATION_URL,
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        key_id = data["id"]

        try:
            # List
            result = runner.invoke(app, [
                "api-key", "list",
                "--coordination-url", COORDINATION_URL,
            ])
            assert result.exit_code == 0
            keys = json.loads(result.output)
            ids = [k["id"] for k in keys]
            assert key_id in ids
        finally:
            # Revoke
            result = runner.invoke(app, [
                "api-key", "revoke", key_id,
                "--coordination-url", COORDINATION_URL,
            ])
            assert result.exit_code == 0

    def test_node_list(self):
        """List nodes via CLI."""
        result = runner.invoke(app, [
            "node", "list",
            "--coordination-url", COORDINATION_URL,
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
