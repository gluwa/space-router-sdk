"""Tests for ``spacerouter status`` command."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import httpx

from spacerouter_cli.main import app
from tests.conftest import parse_json_output


def _ok_response(body=None):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = body or {"status": "healthy"}
    return m


class TestStatus:
    @patch("spacerouter_cli.commands.status.httpx.get")
    def test_all_healthy(self, mock_get, runner, cli_env):
        def side_effect(url, **kwargs):
            if "/readyz" in url:
                return _ok_response({"status": "ready"})
            return _ok_response()

        mock_get.side_effect = side_effect

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["overall"] == "healthy"
        assert data["coordination_api"]["status"] == "healthy"
        assert data["gateway"]["healthy"] is True
        assert data["gateway"]["ready"] is True

    @patch("spacerouter_cli.commands.status.httpx.get")
    def test_coordination_unreachable(self, mock_get, runner, cli_env):
        def side_effect(url, **kwargs):
            if "coordination.spacerouter.org" in url:
                raise httpx.ConnectError("Connection refused")
            if "/readyz" in url:
                return _ok_response({"status": "ready"})
            return _ok_response()

        mock_get.side_effect = side_effect

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        data = parse_json_output(result.output)
        assert data["overall"] == "degraded"
        assert data["coordination_api"]["status"] == "unreachable"

    @patch("spacerouter_cli.commands.status.httpx.get")
    def test_gateway_unreachable(self, mock_get, runner, cli_env):
        def side_effect(url, **kwargs):
            if "gateway.spacerouter.org:8081" in url:
                raise httpx.ConnectError("Connection refused")
            return _ok_response()

        mock_get.side_effect = side_effect

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        data = parse_json_output(result.output)
        assert data["overall"] == "degraded"
        assert data["gateway"]["status"] == "unreachable"

    @patch("spacerouter_cli.commands.status.httpx.get")
    def test_both_unreachable(self, mock_get, runner, cli_env):
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        data = parse_json_output(result.output)
        assert data["overall"] == "degraded"
