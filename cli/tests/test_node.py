"""Tests for ``spacerouter node`` commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from spacerouter.models import Node

from spacerouter_cli.main import app
from tests.conftest import parse_json_output

_SAMPLE_NODE = Node(
    id="node-1",
    endpoint_url="http://192.168.1.100:9090",
    public_ip="73.162.1.1",
    connectivity_type="direct",
    node_type="residential",
    status="online",
    health_score=0.95,
    region="US",
    label=None,
    ip_type="residential",
    ip_region="US",
    as_type="isp",
    identity_address="0xabc",
    staking_address="0xdef",
    collection_address="0xabc",
    created_at="2025-01-01T00:00:00Z",
)


class TestRegisterNode:
    @patch("spacerouter_cli.commands.node._load_identity", return_value="0x" + "ab" * 32)
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_register(self, mock_admin_cls, mock_identity, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.register_node_with_identity.return_value = _SAMPLE_NODE
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "node", "register",
            "--endpoint-url", "http://192.168.1.100:9090",
            "--staking-address", "0xdef",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["id"] == "node-1"
        assert data["identity_address"] == "0xabc"


class TestListNodes:
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_list_success(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.list_nodes.return_value = [_SAMPLE_NODE]
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, ["node", "list"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "node-1"


class TestUpdateNodeStatus:
    @patch("spacerouter_cli.commands.node._load_identity", return_value="0x" + "ab" * 32)
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_update_status(self, mock_admin_cls, mock_identity, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "node", "update-status", "node-1", "--status", "draining",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["ok"] is True


class TestRequestProbe:
    @patch("spacerouter_cli.commands.node._load_identity", return_value="0x" + "ab" * 32)
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_request_probe(self, mock_admin_cls, mock_identity, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, ["node", "request-probe", "node-1"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["ok"] is True


class TestDeleteNode:
    @patch("spacerouter_cli.commands.node._load_identity", return_value="0x" + "ab" * 32)
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_delete(self, mock_admin_cls, mock_identity, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, ["node", "delete", "node-1"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["ok"] is True
