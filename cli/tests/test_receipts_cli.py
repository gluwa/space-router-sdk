"""Tests for the new ``spacerouter receipts`` Leg 1 broker subcommands.

These cover ``receipts pending``, ``receipts sync``, ``receipts list`` —
each in both table and ``--json`` modes — plus the ``--watch`` clean-exit
behaviour on KeyboardInterrupt. The on-chain ``is-settled`` / ``show``
cases live in ``test_escrow_cli.py`` and are NOT touched here.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from spacerouter_cli.main import app
from tests.conftest import parse_json_output, parse_last_json


CLIENT_ADDR = "0x" + "a" * 40
WALLET_ADDR = "0x" + "b" * 40


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def settle_env(monkeypatch):
    """Provide enough env for ConsumerSettlementClient to construct."""
    # ConsumerSettlementClient does Account.from_key on init, so we need a
    # syntactically valid key (32-byte hex).
    monkeypatch.setenv("SR_ESCROW_PRIVATE_KEY", "0x" + "1" * 64)
    monkeypatch.setenv("SR_GATEWAY_MANAGEMENT_URL",
                       "https://spacerouter-proxy-gateway-test.fly.dev")


def _pending_payload(n: int = 2) -> dict:
    receipts = []
    for i in range(n):
        receipts.append({
            "request_uuid": f"00000000-0000-0000-0000-00000000000{i}",
            "client_address": CLIENT_ADDR if i == 0 else WALLET_ADDR,
            "node_address": "0x" + "00" * 12 + "9e46051b44b1639a8a9f8a53041c6f121c0fe789",
            "data_amount": 1024 * (i + 1),
            "total_price": str(1_000_000_000_000_000 * (i + 1)),
            "tunnel_request_id": f"tun-{i}",
            "created_at": "2026-04-27T10:00:00+00:00",
        })
    return {
        "receipts": receipts,
        "domain": {
            "name": "TokenPaymentEscrow",
            "version": "1",
            "chainId": 102031,
            "verifyingContract": "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
        },
    }


# ── pending ────────────────────────────────────────────────────────


class TestReceiptsPending:
    def test_pending_json(self, runner, settle_env):
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            async def _fake_fetch(limit=50):
                return _pending_payload(2)
            inst.fetch_pending = _fake_fetch
            cls.return_value = inst

            result = runner.invoke(app, ["receipts", "pending", "--json"])
            assert result.exit_code == 0, result.output
            data = parse_json_output(result.output)
            assert data["pending_count"] == 2
            assert data["receipts"][0]["data_amount"] == 1024
            assert data["receipts"][1]["total_price"] == 2_000_000_000_000_000
            assert data["domain"]["chainId"] == 102031

    def test_pending_table(self, runner, settle_env):
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            async def _fake_fetch(limit=50):
                return _pending_payload(1)
            inst.fetch_pending = _fake_fetch
            cls.return_value = inst

            result = runner.invoke(app, ["receipts", "pending"])
            assert result.exit_code == 0, result.output
            assert "Pending Leg 1 receipts" in result.output
            assert "request_uuid" in result.output

    def test_pending_empty_table(self, runner, settle_env):
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            async def _fake_fetch(limit=50):
                return {"receipts": [], "domain": {}}
            inst.fetch_pending = _fake_fetch
            cls.return_value = inst

            result = runner.invoke(app, ["receipts", "pending"])
            assert result.exit_code == 0
            assert "No pending Leg 1 receipts" in result.output

    def test_missing_key_fails(self, runner, monkeypatch):
        monkeypatch.delenv("SR_ESCROW_PRIVATE_KEY", raising=False)
        result = runner.invoke(app, ["receipts", "pending", "--json"])
        assert result.exit_code != 0


# ── sync ───────────────────────────────────────────────────────────


class TestReceiptsSync:
    def test_sync_json_happy_path(self, runner, settle_env):
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            async def _fake_sync(limit=50):
                return {
                    "accepted": ["a", "b"],
                    "rejected": [],
                    "pending_count": 2,
                }
            inst.sync_receipts = _fake_sync
            cls.return_value = inst

            result = runner.invoke(app, ["receipts", "sync", "--json"])
            assert result.exit_code == 0, result.output
            data = parse_json_output(result.output)
            assert data["accepted"] == ["a", "b"]
            assert data["rejected"] == []
            assert data["pending_count"] == 2

    def test_sync_surfaces_rejection_reasons(self, runner, settle_env):
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            async def _fake_sync(limit=50):
                return {
                    "accepted": ["good-uuid"],
                    "rejected": [
                        {"request_uuid": "bad-1", "reason": "eip712_signer_mismatch"},
                        {"request_uuid": "bad-2", "reason": "not_pending"},
                    ],
                    "pending_count": 3,
                }
            inst.sync_receipts = _fake_sync
            cls.return_value = inst

            # JSON mode — reasons in payload.
            result = runner.invoke(app, ["receipts", "sync", "--json"])
            assert result.exit_code == 0, result.output
            data = parse_json_output(result.output)
            assert len(data["rejected"]) == 2
            reasons = [r["reason"] for r in data["rejected"]]
            assert "eip712_signer_mismatch" in reasons
            assert "not_pending" in reasons

            # Table mode — reasons in stdout text.
            result = runner.invoke(app, ["receipts", "sync"])
            assert result.exit_code == 0, result.output
            assert "eip712_signer_mismatch" in result.output
            assert "not_pending" in result.output

    def test_sync_table(self, runner, settle_env):
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            async def _fake_sync(limit=50):
                return {"accepted": ["a"], "rejected": [], "pending_count": 1}
            inst.sync_receipts = _fake_sync
            cls.return_value = inst

            result = runner.invoke(app, ["receipts", "sync"])
            assert result.exit_code == 0
            assert "Leg 1 sync result" in result.output
            assert "accepted" in result.output

    def test_watch_exits_on_keyboard_interrupt(self, runner, settle_env):
        """``--watch`` should swallow KeyboardInterrupt and emit summary."""
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls, patch(
            "spacerouter_cli.commands.receipts.time.sleep"
        ) as mock_sleep:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            iter_count = {"n": 0}
            async def _fake_sync(limit=50):
                return {
                    "accepted": ["ok-1"],
                    "rejected": [
                        {"request_uuid": "r-1", "reason": "not_pending"},
                    ],
                    "pending_count": 2,
                }
            inst.sync_receipts = _fake_sync
            cls.return_value = inst

            # KeyboardInterrupt on first sleep -> exactly one iteration ran.
            def _raise(*_a, **_kw):
                iter_count["n"] += 1
                raise KeyboardInterrupt
            mock_sleep.side_effect = _raise

            result = runner.invoke(
                app, ["receipts", "sync", "--watch", "1", "--json"],
            )
            assert result.exit_code == 0, result.output
            # Last JSON object is the watch_summary.
            summary = parse_last_json(result.output)
            assert "watch_summary" in summary
            assert summary["watch_summary"]["iterations"] == 1
            assert summary["watch_summary"]["accepted_total"] == 1
            assert summary["watch_summary"]["rejected_total"] == 1
            assert iter_count["n"] == 1


# ── list ───────────────────────────────────────────────────────────


class TestReceiptsList:
    def test_list_groups_by_tunnel_json(self, runner, settle_env):
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            async def _fake_fetch(limit=50):
                return _pending_payload(2)
            inst.fetch_pending = _fake_fetch
            cls.return_value = inst

            result = runner.invoke(app, ["receipts", "list", "--json"])
            assert result.exit_code == 0, result.output
            data = parse_json_output(result.output)
            assert data["pending_count"] == 2
            tunnels = {g["tunnel_request_id"] for g in data["groups"]}
            assert tunnels == {"tun-0", "tun-1"}

    def test_list_filters_by_client(self, runner, settle_env):
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            async def _fake_fetch(limit=50):
                return _pending_payload(2)
            inst.fetch_pending = _fake_fetch
            cls.return_value = inst

            result = runner.invoke(app, [
                "receipts", "list", "--json", "--client", CLIENT_ADDR,
            ])
            assert result.exit_code == 0, result.output
            data = parse_json_output(result.output)
            assert data["pending_count"] == 1
            assert data["filter_client"] == CLIENT_ADDR

    def test_list_table(self, runner, settle_env):
        with patch(
            "spacerouter_cli.commands.receipts.ConsumerSettlementClient"
        ) as cls:
            inst = MagicMock()
            inst.address = WALLET_ADDR
            async def _fake_fetch(limit=50):
                return _pending_payload(1)
            inst.fetch_pending = _fake_fetch
            cls.return_value = inst

            result = runner.invoke(app, ["receipts", "list"])
            assert result.exit_code == 0
            assert "Tunnel tun-0" in result.output


# ── existing on-chain commands still work ──────────────────────────


class TestSubAppsRegistered:
    def test_new_subcommands_appear_in_help(self, runner):
        result = runner.invoke(app, ["receipts", "--help"])
        assert result.exit_code == 0
        for cmd in ("pending", "sync", "list", "is-settled", "show"):
            assert cmd in result.output
