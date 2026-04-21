"""Tests for ``spacerouter escrow`` and ``spacerouter receipts`` sub-apps."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from spacerouter_cli.main import app
from tests.conftest import parse_json_output


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def escrow_env(monkeypatch):
    monkeypatch.setenv("SR_ESCROW_CHAIN_RPC",
                       "https://rpc.cc3-testnet.creditcoin.network")
    monkeypatch.setenv("SR_ESCROW_CONTRACT_ADDRESS",
                       "0xC5740e4e9175301a24FB6d22bA184b8ec0762852")


@pytest.fixture
def mock_escrow_client():
    """Patch EscrowClient so no real RPC calls go out."""
    with patch(
        "spacerouter_cli.commands.escrow.EscrowClient"
    ) as cls:
        inst = MagicMock()
        cls.return_value = inst
        yield inst


class TestEscrowBalance:
    def test_balance_emits_wei_and_space(
        self, runner, escrow_env, mock_escrow_client,
    ):
        mock_escrow_client.balance.return_value = 5 * 10**18
        result = runner.invoke(app, [
            "escrow", "balance", "0xabcd" + "0" * 36,
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["escrow_balance_wei"] == 5 * 10**18
        assert data["escrow_balance_space"] == 5.0

    def test_balance_requires_rpc(self, runner, monkeypatch):
        monkeypatch.delenv("SR_ESCROW_CHAIN_RPC", raising=False)
        monkeypatch.delenv("SR_ESCROW_CONTRACT_ADDRESS", raising=False)
        result = runner.invoke(app, [
            "escrow", "balance", "0xabcd" + "0" * 36,
        ])
        assert result.exit_code != 0


class TestWithdrawalRequest:
    def test_pending_withdrawal_fields(
        self, runner, escrow_env, mock_escrow_client,
    ):
        mock_escrow_client.withdrawal_request.return_value = (
            10**18, 1_800_000_000, True,
        )
        result = runner.invoke(app, [
            "escrow", "withdrawal-request", "0x" + "a" * 40,
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["has_pending_withdrawal"] is True
        assert data["amount_wei"] == 10**18
        assert data["amount_space"] == 1.0
        assert data["unlock_at_epoch_seconds"] == 1_800_000_000


class TestWithdrawalDelay:
    def test_surfaces_days(self, runner, escrow_env, mock_escrow_client):
        mock_escrow_client.withdrawal_delay.return_value = 5 * 86400
        result = runner.invoke(app, ["escrow", "withdrawal-delay"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["withdrawal_delay_seconds"] == 432_000
        assert data["withdrawal_delay_days"] == 5.0


class TestDeposit:
    def test_deposit_returns_tx_hash(
        self, runner, escrow_env, mock_escrow_client, monkeypatch,
    ):
        monkeypatch.setenv("SR_ESCROW_PRIVATE_KEY", "0x" + "f" * 64)
        mock_escrow_client.deposit.return_value = "0xabc123"
        mock_escrow_client.address = "0x" + "a" * 40
        result = runner.invoke(app, ["escrow", "deposit", "1000000000000000000"])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["tx_hash"] == "0xabc123"
        assert data["action"] == "deposit"
        mock_escrow_client.deposit.assert_called_once_with(10**18)


class TestReceiptsIsSettled:
    def test_returns_on_chain_state(
        self, runner, escrow_env, mock_escrow_client,
    ):
        mock_escrow_client.is_nonce_used.return_value = True
        result = runner.invoke(app, [
            "receipts", "is-settled",
            "0x" + "a" * 40,
            "9f8e5c21-1234-4567-89ab-cdef01234567",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["settled_on_chain"] is True
        assert data["request_uuid"] == "9f8e5c21-1234-4567-89ab-cdef01234567"

    def test_unsettled_returns_false(
        self, runner, escrow_env, mock_escrow_client,
    ):
        mock_escrow_client.is_nonce_used.return_value = False
        result = runner.invoke(app, [
            "receipts", "is-settled",
            "0x" + "a" * 40,
            "11111111-2222-3333-4444-555555555555",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["settled_on_chain"] is False


class TestReceiptsShow:
    def test_emits_status_field(
        self, runner, escrow_env, mock_escrow_client,
    ):
        mock_escrow_client.is_nonce_used.return_value = False
        result = runner.invoke(app, [
            "receipts", "show",
            "0x" + "b" * 40,
            "22222222-3333-4444-5555-666666666666",
        ])
        assert result.exit_code == 0
        data = parse_json_output(result.output)
        assert data["status"] == "unclaimed_on_chain"


class TestSubAppsRegistered:
    def test_escrow_appears_in_help(self, runner):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "escrow" in result.output
        assert "receipts" in result.output
