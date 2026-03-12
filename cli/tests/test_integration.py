"""Integration tests for the SpaceRouter CLI.

These tests hit the **live** Coordination API and proxy gateway at
``gateway.spacerouter.org``.  They are gated behind the ``SR_INTEGRATION``
environment variable so they never run in normal CI:

    SR_INTEGRATION=1 pytest tests/test_integration.py -v
"""

from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

_RUN = os.environ.get("SR_INTEGRATION", "") == "1"
pytestmark = pytest.mark.skipif(not _RUN, reason="SR_INTEGRATION not set")

from spacerouter_cli.main import app  # noqa: E402


runner = CliRunner()

COORDINATION_URL = os.environ.get(
    "SR_COORDINATION_API_URL", "https://coordination.spacerouter.org"
)
GATEWAY_URL = os.environ.get(
    "SR_GATEWAY_URL", "http://gateway.spacerouter.org:8080"
)


class TestCLIIntegration:
    """End-to-end: create key via CLI -> proxy request -> revoke."""

    def test_full_lifecycle(self):
        # 1. Create an ephemeral API key via the CLI.
        result = runner.invoke(app, [
            "api-key", "create",
            "--name", "integration-test-cli",
            "--coordination-url", COORDINATION_URL,
        ])
        assert result.exit_code == 0, f"create failed: {result.output}"
        data = json.loads(result.output)
        api_key = data["api_key"]
        key_id = data["id"]
        assert api_key.startswith("sr_live_")

        try:
            # 2. Proxy a GET request through the gateway.
            result = runner.invoke(app, [
                "request", "get", "https://httpbin.org/ip",
                "--api-key", api_key,
                "--gateway-url", GATEWAY_URL,
            ])
            assert result.exit_code == 0, f"request failed: {result.output}"
            data = json.loads(result.output)
            assert data["status_code"] == 200
            assert "origin" in data["body"]

        finally:
            # 3. Cleanup: revoke the key.
            result = runner.invoke(app, [
                "api-key", "revoke", key_id,
                "--coordination-url", COORDINATION_URL,
            ])
            assert result.exit_code == 0

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
