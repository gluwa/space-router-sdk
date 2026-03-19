"""Tests for ``spacerouter node`` commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from spacerouter.models import Node, RegisterChallenge, RegisterResult

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
    wallet_address="0xabc",
    created_at="2025-01-01T00:00:00Z",
    gateway_ca_cert="CERT",
)


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


class TestRegisterNode:
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_register_success(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.register_node.return_value = _SAMPLE_NODE
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "node", "register",
            "--endpoint-url", "http://192.168.1.100:9090",
            "--wallet-address", "0xabc",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["id"] == "node-1"


class TestUpdateNodeStatus:
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_update_status(self, mock_admin_cls, runner, cli_env):
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


class TestDeleteNode:
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_delete(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, ["node", "delete", "node-1"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["ok"] is True


class TestRegisterChallenge:
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_challenge(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.get_register_challenge.return_value = RegisterChallenge(
            nonce="abc123", expires_in=300
        )
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "node", "register-challenge", "--address", "0xwallet",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["nonce"] == "abc123"


class TestRegisterVerify:
    @patch("spacerouter_cli.commands.node.SpaceRouterAdmin")
    def test_verify(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.verify_and_register.return_value = RegisterResult(
            status="registered",
            node_id="node-new",
            address="0xwallet",
            endpoint_url="http://node:9090",
            gateway_ca_cert="CERT",
        )
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "node", "register-verify",
            "--address", "0xwallet",
            "--endpoint-url", "http://node:9090",
            "--signed-nonce", "signed-abc",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["status"] == "registered"
