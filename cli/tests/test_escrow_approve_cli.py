"""Tests for ``spacerouter escrow approve``.

The approve command builds a fresh Web3 client to send the ERC-20 tx
(it doesn't go through ``EscrowClient.deposit``'s auto-approve), so we
mock both ``EscrowClient`` (for token-address resolution) and ``Web3``
(for the actual send). Behaviour matrix:

* explicit ``--token`` overrides escrow-discovered token.
* missing private key fails fast.
* happy path emits ``tx_hash`` and ``spender`` (the escrow address).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from spacerouter_cli.main import app
from tests.conftest import parse_json_output


ESCROW = "0xC5740e4e9175301a24FB6d22bA184b8ec0762852"
TOKEN = "0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA"
WALLET = "0x" + "a" * 40


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def approve_env(monkeypatch):
    monkeypatch.setenv("SR_ESCROW_CHAIN_RPC", "https://rpc.cc3-testnet.creditcoin.network")
    monkeypatch.setenv("SR_ESCROW_CONTRACT_ADDRESS", ESCROW)
    monkeypatch.setenv("SR_ESCROW_PRIVATE_KEY", "0x" + "f" * 64)


def _wire_mocks(escrow_cls, web3_cls, *, with_token: bool = True):
    """Wire the EscrowClient + Web3 mocks so approve() can run."""
    # EscrowClient: account, _contract_address, _token_contract.
    escrow_inst = MagicMock()
    escrow_inst._contract_address = ESCROW
    account_mock = MagicMock()
    account_mock.address = WALLET
    account_mock.key = b"\x01" * 32
    escrow_inst._account = account_mock
    if with_token:
        token_contract_mock = MagicMock()
        token_contract_mock.address = TOKEN
        escrow_inst._token_contract = token_contract_mock
    else:
        escrow_inst._token_contract = None
    escrow_cls.return_value = escrow_inst

    # Web3 instance: chain id, nonce, contract.approve build_transaction,
    # estimate_gas, send_raw_transaction, wait_for_transaction_receipt.
    w3_inst = MagicMock()
    w3_inst.eth.chain_id = 102031
    w3_inst.eth.get_transaction_count.return_value = 1

    erc20_mock = MagicMock()
    approve_call = MagicMock()
    approve_call.build_transaction.return_value = {
        "from": WALLET, "nonce": 1, "chainId": 102031, "gas": 100_000,
    }
    erc20_mock.functions.approve.return_value = approve_call
    w3_inst.eth.contract.return_value = erc20_mock
    w3_inst.eth.estimate_gas.return_value = 60_000

    signed_tx = MagicMock()
    signed_tx.raw_transaction = b"\xab\xcd"
    w3_inst.eth.account.sign_transaction.return_value = signed_tx
    tx_hash_bytes = MagicMock()
    tx_hash_bytes.hex.return_value = "0xtxhash"
    w3_inst.eth.send_raw_transaction.return_value = tx_hash_bytes
    w3_inst.eth.wait_for_transaction_receipt.return_value = {"status": 1}

    web3_cls.return_value = w3_inst
    return escrow_inst, w3_inst, erc20_mock


class TestEscrowApprove:
    def test_happy_path_uses_discovered_token(self, runner, approve_env):
        with patch("spacerouter_cli.commands.escrow.EscrowClient") as escrow_cls, \
             patch("spacerouter_cli.commands.escrow.Web3") as web3_cls:
            _wire_mocks(escrow_cls, web3_cls)
            result = runner.invoke(app, [
                "escrow", "approve", "1000000000000000000",
            ])
            assert result.exit_code == 0, result.output
            data = parse_json_output(result.output)
            assert data["action"] == "approve"
            assert data["amount_wei"] == 10**18
            assert data["spender"] == ESCROW
            assert data["token"] == TOKEN
            assert data["tx_hash"] == "0xtxhash"

    def test_explicit_token_override(self, runner, approve_env):
        custom_token = "0x" + "9" * 40
        with patch("spacerouter_cli.commands.escrow.EscrowClient") as escrow_cls, \
             patch("spacerouter_cli.commands.escrow.Web3") as web3_cls:
            _wire_mocks(escrow_cls, web3_cls, with_token=False)
            result = runner.invoke(app, [
                "escrow", "approve", "5",
                "--token", custom_token,
            ])
            assert result.exit_code == 0, result.output
            data = parse_json_output(result.output)
            assert data["token"].lower() == custom_token.lower()

    def test_requires_private_key(self, runner, monkeypatch):
        monkeypatch.setenv("SR_ESCROW_CHAIN_RPC", "https://rpc.example")
        monkeypatch.setenv("SR_ESCROW_CONTRACT_ADDRESS", ESCROW)
        monkeypatch.delenv("SR_ESCROW_PRIVATE_KEY", raising=False)
        with patch("spacerouter_cli.commands.escrow.EscrowClient") as escrow_cls:
            inst = MagicMock()
            inst._account = None
            inst._token_contract = MagicMock(address=TOKEN)
            inst._contract_address = ESCROW
            escrow_cls.return_value = inst
            result = runner.invoke(app, [
                "escrow", "approve", "1",
            ])
            assert result.exit_code != 0

    def test_negative_amount_rejected(self, runner, approve_env):
        with patch("spacerouter_cli.commands.escrow.EscrowClient"):
            result = runner.invoke(app, [
                "escrow", "approve", "-1",
            ])
            assert result.exit_code != 0

    def test_help_lists_approve(self, runner):
        result = runner.invoke(app, ["escrow", "--help"])
        assert result.exit_code == 0
        assert "approve" in result.output
