"""Tests for ``spacerouter api-key`` commands."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from spacerouter_cli.main import app
from tests.conftest import parse_json_output


def _mock_api_key(id="key-1", name="agent", api_key="sr_live_abc", rate_limit_rpm=60):
    m = MagicMock()
    m.id = id
    m.name = name
    m.api_key = api_key
    m.rate_limit_rpm = rate_limit_rpm
    return m


def _mock_api_key_info(
    id="key-1", name="agent", key_prefix="sr_live_abc1",
    rate_limit_rpm=60, is_active=True, created_at="2025-01-01T00:00:00Z",
):
    m = MagicMock()
    m.model_dump.return_value = {
        "id": id, "name": name, "key_prefix": key_prefix,
        "rate_limit_rpm": rate_limit_rpm, "is_active": is_active,
        "created_at": created_at,
    }
    return m


class TestCreate:
    @patch("spacerouter_cli.commands.api_key.SpaceRouterAdmin")
    def test_create_key(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.create_api_key.return_value = _mock_api_key()
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, ["api-key", "create", "--name", "agent"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["name"] == "agent"
        assert data["api_key"] == "sr_live_abc"
        assert data["rate_limit_rpm"] == 60

    @patch("spacerouter_cli.commands.api_key.SpaceRouterAdmin")
    def test_create_with_rate_limit(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.create_api_key.return_value = _mock_api_key(rate_limit_rpm=120)
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "api-key", "create", "--name", "fast-agent", "--rate-limit", "120"
        ])
        assert result.exit_code == 0
        mock_admin.create_api_key.assert_called_once_with("fast-agent", rate_limit_rpm=120)


class TestList:
    @patch("spacerouter_cli.commands.api_key.SpaceRouterAdmin")
    def test_list_keys(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.list_api_keys.return_value = [
            _mock_api_key_info(id="k1", name="a1"),
            _mock_api_key_info(id="k2", name="a2"),
        ]
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, ["api-key", "list"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert len(data) == 2
        assert data[0]["id"] == "k1"
        assert data[1]["id"] == "k2"


class TestRevoke:
    @patch("spacerouter_cli.commands.api_key.SpaceRouterAdmin")
    def test_revoke_key(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, ["api-key", "revoke", "key-uuid-123"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["ok"] is True
        assert data["revoked_key_id"] == "key-uuid-123"
        mock_admin.revoke_api_key.assert_called_once_with("key-uuid-123")
