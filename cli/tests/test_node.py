"""Tests for ``spacerouter node`` commands."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import httpx

from spacerouter_cli.main import app
from tests.conftest import parse_json_output

NODES_RESPONSE = [
    {
        "id": "node-1",
        "endpoint_url": "http://192.168.1.100:9090",
        "node_type": "residential",
        "status": "online",
        "health_score": 0.95,
        "region": "us-west",
    },
    {
        "id": "node-2",
        "endpoint_url": "http://10.0.0.50:9090",
        "node_type": "residential",
        "status": "offline",
        "health_score": 0.5,
        "region": "eu-west",
    },
]


class TestListNodes:
    @patch("spacerouter_cli.commands.node.httpx.get")
    def test_list_success(self, mock_get, runner, cli_env):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = NODES_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = runner.invoke(app, ["node", "list"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert len(data) == 2
        assert data[0]["id"] == "node-1"
        assert data[1]["status"] == "offline"

    @patch("spacerouter_cli.commands.node.httpx.get")
    def test_list_connection_error(self, mock_get, runner, cli_env):
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        result = runner.invoke(app, ["node", "list"])
        assert result.exit_code == 5
        data = parse_json_output(result.output)
        assert data["error"] == "connection_error"

    @patch("spacerouter_cli.commands.node.httpx.get")
    def test_custom_coordination_url(self, mock_get, runner, cli_env):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = runner.invoke(app, [
            "node", "list", "--coordination-url", "http://custom:9000"
        ])
        assert result.exit_code == 0
        mock_get.assert_called_once_with("http://custom:9000/nodes", timeout=10.0)
