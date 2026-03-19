"""Tests for ``spacerouter billing`` commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from spacerouter.models import BillingReissueResult, CheckoutSession

from spacerouter_cli.main import app
from tests.conftest import parse_json_output


class TestCheckout:
    @patch("spacerouter_cli.commands.billing.SpaceRouterAdmin")
    def test_checkout_success(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.create_checkout.return_value = CheckoutSession(
            checkout_url="https://checkout.stripe.com/session"
        )
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "billing", "checkout", "--email", "user@example.com",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert "stripe.com" in data["checkout_url"]


class TestVerifyEmail:
    @patch("spacerouter_cli.commands.billing.SpaceRouterAdmin")
    def test_verify_success(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "billing", "verify", "--token", "tok-123",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["ok"] is True


class TestReissue:
    @patch("spacerouter_cli.commands.billing.SpaceRouterAdmin")
    def test_reissue_success(self, mock_admin_cls, runner, cli_env):
        mock_admin = MagicMock()
        mock_admin.__enter__ = MagicMock(return_value=mock_admin)
        mock_admin.__exit__ = MagicMock(return_value=False)
        mock_admin.reissue_api_key.return_value = BillingReissueResult(
            new_api_key="sr_live_new_key"
        )
        mock_admin_cls.return_value = mock_admin

        result = runner.invoke(app, [
            "billing", "reissue",
            "--email", "user@example.com",
            "--token", "tok-456",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["new_api_key"] == "sr_live_new_key"
