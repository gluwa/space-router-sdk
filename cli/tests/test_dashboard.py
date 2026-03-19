"""Tests for ``spacerouter dashboard`` commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from spacerouter.models import Transfer, TransferPage

from spacerouter_cli.main import app
from tests.conftest import parse_json_output


class TestTransfers:
    @patch("spacerouter_cli.commands.dashboard.SpaceRouterAdmin")
    def test_transfers_success(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.get_transfers.return_value = TransferPage(
            page=1,
            total_pages=3,
            total_bytes=2048,
            transfers=[
                Transfer(
                    request_id="req-1",
                    bytes=512,
                    method="GET",
                    target_host="example.com",
                    created_at="2025-01-01T00:00:00Z",
                ),
            ],
        )
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "dashboard", "transfers",
            "--wallet-address", "0xabc",
            "--page", "1",
            "--page-size", "10",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["total_pages"] == 3
        assert len(data["transfers"]) == 1
        assert data["transfers"][0]["request_id"] == "req-1"
