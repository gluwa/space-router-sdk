"""Tests for ``spacerouter request`` commands."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from spacerouter_cli.main import app
from tests.conftest import parse_json_output


def _mock_proxy_response(
    status_code: int = 200,
    text: str = '{"origin": "73.162.1.1"}',
    headers: dict | None = None,
    request_id: str | None = "req-1",
):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    all_headers = dict(headers or {})
    if request_id:
        all_headers["x-spacerouter-request-id"] = request_id
    resp.headers = all_headers
    resp.request_id = request_id
    return resp


class TestGet:
    def test_missing_api_key(self, runner):
        result = runner.invoke(app, ["request", "get", "http://example.com"])
        assert result.exit_code == 1
        data = parse_json_output(result.output)
        assert data["error"] == "configuration_error"

    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_success_json(self, mock_sr_cls, runner, cli_env):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = _mock_proxy_response()
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, ["request", "get", "http://example.com"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["status_code"] == 200
        assert data["spacerouter"]["request_id"] == "req-1"
        assert data["body"]["origin"] == "73.162.1.1"

    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_success_raw(self, mock_sr_cls, runner, cli_env):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = _mock_proxy_response(text="hello raw")
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, ["request", "get", "http://example.com", "--output", "raw"])
        assert result.exit_code == 0
        assert result.output.strip() == "hello raw"

    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_custom_headers(self, mock_sr_cls, runner, cli_env):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = _mock_proxy_response()
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, [
            "request", "get", "http://example.com",
            "-H", "Accept: application/json",
            "-H", "X-Custom: value",
        ])
        assert result.exit_code == 0
        call_kwargs = mock_client.request.call_args
        assert call_kwargs[1]["headers"]["Accept"] == "application/json"
        assert call_kwargs[1]["headers"]["X-Custom"] == "value"

    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_auth_error(self, mock_sr_cls, runner, cli_env):
        from spacerouter.exceptions import AuthenticationError

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = AuthenticationError(
            "Invalid API key", status_code=407, request_id="req-err"
        )
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, ["request", "get", "http://example.com"])
        assert result.exit_code == 2
        data = parse_json_output(result.output)
        assert data["error"] == "authentication_error"

    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_rate_limit_error(self, mock_sr_cls, runner, cli_env):
        from spacerouter.exceptions import RateLimitError

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = RateLimitError(
            "Rate limit exceeded", retry_after=42, status_code=429, request_id="req-rl"
        )
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, ["request", "get", "http://example.com"])
        assert result.exit_code == 3
        data = parse_json_output(result.output)
        assert data["error"] == "rate_limit_error"
        assert data["retry_after"] == 42

    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_no_nodes_error(self, mock_sr_cls, runner, cli_env):
        from spacerouter.exceptions import NoNodesAvailableError

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = NoNodesAvailableError(
            "No nodes", status_code=503, request_id="req-nn"
        )
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, ["request", "get", "http://example.com"])
        assert result.exit_code == 4
        data = parse_json_output(result.output)
        assert data["error"] == "no_nodes_available"


class TestPost:
    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_post_with_data(self, mock_sr_cls, runner, cli_env):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = _mock_proxy_response(
            status_code=201, text='{"id": "new"}'
        )
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, [
            "request", "post", "http://example.com/items",
            "--data", '{"name": "test"}',
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["status_code"] == 201
        call_kwargs = mock_client.request.call_args
        assert call_kwargs[1]["json"] == {"name": "test"}

    def test_post_invalid_json(self, runner, cli_env):
        result = runner.invoke(app, [
            "request", "post", "http://example.com",
            "--data", "not-json",
        ])
        assert result.exit_code == 1
        data = parse_json_output(result.output)
        assert data["error"] == "configuration_error"
        assert "JSON" in data["message"]


class TestRegion:
    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_passes_region(self, mock_sr_cls, runner, cli_env):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = _mock_proxy_response()
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, [
            "request", "get", "http://example.com",
            "--region", "US",
        ])
        assert result.exit_code == 0
        mock_sr_cls.assert_called_once()
        call_kwargs = mock_sr_cls.call_args
        assert call_kwargs[1]["region"] == "US"


class TestIpType:
    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_passes_ip_type(self, mock_sr_cls, runner, cli_env):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = _mock_proxy_response()
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, [
            "request", "get", "http://example.com",
            "--ip-type", "residential",
        ])
        assert result.exit_code == 0
        mock_sr_cls.assert_called_once()
        call_kwargs = mock_sr_cls.call_args
        assert call_kwargs[1]["ip_type"] == "residential"

    @patch("spacerouter_cli.commands.request.SpaceRouter")
    def test_passes_region_and_ip_type(self, mock_sr_cls, runner, cli_env):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = _mock_proxy_response()
        mock_sr_cls.return_value = mock_client

        result = runner.invoke(app, [
            "request", "get", "http://example.com",
            "--region", "US",
            "--ip-type", "mobile",
        ])
        assert result.exit_code == 0
        call_kwargs = mock_sr_cls.call_args
        assert call_kwargs[1]["region"] == "US"
        assert call_kwargs[1]["ip_type"] == "mobile"
