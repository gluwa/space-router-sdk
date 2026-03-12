"""Tests for ``spacerouter config`` commands."""

from __future__ import annotations

import json
from unittest.mock import patch

from spacerouter_cli.main import app
from tests.conftest import parse_json_output


class TestConfigShow:
    def test_show_defaults(self, runner):
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["gateway_url"] == "https://gateway.spacerouter.org:8080"
        assert data["coordination_api_url"] == "https://coordination.spacerouter.org"
        assert data["timeout"] == 30.0
        assert data["api_key"] is None

    def test_show_with_env(self, runner, cli_env):
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["api_key"] == "sr_live_test****"


class TestConfigSet:
    @patch("spacerouter_cli.commands.config_cmd.save_config")
    def test_set_gateway_url(self, mock_save, runner):
        result = runner.invoke(app, [
            "config", "set", "gateway_url", "http://new-gw:8080"
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["ok"] is True
        assert data["key"] == "gateway_url"
        assert data["value"] == "http://new-gw:8080"
        mock_save.assert_called_once_with({"gateway_url": "http://new-gw:8080"})

    @patch("spacerouter_cli.commands.config_cmd.save_config")
    def test_set_api_key_masked(self, mock_save, runner):
        result = runner.invoke(app, [
            "config", "set", "api_key", "sr_live_secret_value_123"
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert "****" in data["value"]
        mock_save.assert_called_once_with({"api_key": "sr_live_secret_value_123"})

    def test_set_invalid_key(self, runner):
        result = runner.invoke(app, ["config", "set", "invalid_key", "value"])
        assert result.exit_code == 1
        data = parse_json_output(result.output)
        assert data["error"] == "invalid_config_key"


class TestVersion:
    def test_version_flag(self, runner):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert "version" in data
