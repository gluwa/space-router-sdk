"""Tests for ``spacerouter regions`` command."""
from __future__ import annotations

from unittest.mock import patch

import httpx

from spacerouter_cli.main import app
from tests.conftest import parse_json_output


class TestRegions:
    @patch("spacerouter_cli.commands.regions.httpx.get")
    def test_regions_success(self, mock_get, runner, cli_env):
        mock_get.return_value = httpx.Response(200, json={
            "regions": [{"region": "US", "ip_types": ["residential"]}],
            "brightdata_available": True,
        })
        result = runner.invoke(app, ["regions"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert len(data["regions"]) == 1
        assert data["regions"][0]["region"] == "US"

    @patch("spacerouter_cli.commands.regions.httpx.get")
    def test_regions_with_ip_type(self, mock_get, runner, cli_env):
        mock_get.return_value = httpx.Response(200, json={
            "regions": [],
            "brightdata_available": False,
        })
        result = runner.invoke(app, ["regions", "--ip-type", "mobile"])
        assert result.exit_code == 0
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"] == {"ip_type": "mobile"}

    @patch("spacerouter_cli.commands.regions.httpx.get")
    def test_regions_error(self, mock_get, runner, cli_env):
        mock_get.return_value = httpx.Response(500, text="error")
        result = runner.invoke(app, ["regions"])
        assert result.exit_code == 5
