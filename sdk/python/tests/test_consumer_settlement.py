"""Unit tests for the consumer-side Leg 1 settlement client.

Exercises the out-of-band replacement for the broken in-band TCP
receipt exchange: ``fetch_pending`` → sign each with EIP-712 →
``submit_signatures`` → ``sync_receipts`` as the one-shot wrapper.

No real network: httpx is monkeypatched with a fake handler that
returns canned JSON.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from unittest.mock import patch

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from spacerouter.payment.consumer_settlement import ConsumerSettlementClient
from spacerouter.payment.eip712 import (
    EIP712Domain,
    Receipt,
    recover_receipt_signer,
)


CONSUMER_KEY = (
    "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937"
)
DOMAIN = EIP712Domain(
    name="TokenPaymentEscrow",
    version="1",
    chain_id=102031,
    verifying_contract="0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
)


def _consumer_addr() -> str:
    return Account.from_key(CONSUMER_KEY).address


def _pending_payload(receipts: list[dict]) -> dict:
    return {"receipts": receipts, "domain": DOMAIN.to_dict()}


def _receipt_row(**overrides) -> dict:
    base = {
        "request_uuid": str(uuid.uuid4()),
        "client_address": _consumer_addr().lower(),
        "node_address": "0x" + "bb" * 32,
        "data_amount": 1024,
        "total_price": 100,
        "tunnel_request_id": "tun-1",
        "created_at": "2026-04-21T10:00:00+00:00",
    }
    base.update(overrides)
    return base


@pytest.fixture
def client():
    return ConsumerSettlementClient(
        gateway_url="https://gateway.example", private_key=CONSUMER_KEY,
    )


class _MockTransport(httpx.AsyncBaseTransport):
    """Routes requests to a user-provided handler — lets tests see the
    outgoing request and provide the response directly."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[httpx.Request] = []

    async def handle_async_request(self, request):
        self.calls.append(request)
        status, body = self.handler(request)
        return httpx.Response(
            status_code=status,
            content=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
            request=request,
        )


def _install_transport(handler):
    """Monkeypatch httpx.AsyncClient to use our transport."""
    transport = _MockTransport(handler)
    orig = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("verify", None)
        orig(self, *args, **kwargs)

    return transport, patched


# ── fetch_pending ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_pending_authed_and_parsed(client):
    seeded = [_receipt_row(), _receipt_row()]
    def handler(req):
        assert req.url.path == "/leg1/pending"
        assert req.url.params["address"] == _consumer_addr()
        assert int(req.url.params["ts"])
        assert req.url.params["sig"].startswith("0x")
        return 200, _pending_payload(seeded)

    transport, patched = _install_transport(handler)
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.fetch_pending()
    assert len(result["receipts"]) == 2
    assert result["domain"]["name"] == "TokenPaymentEscrow"
    # Outer EIP-191 auth verifies
    q = dict(transport.calls[0].url.params)
    recovered = Account.recover_message(
        encode_defunct(
            text=f"space-router:leg1-list-pending:{_consumer_addr().lower()}:{q['ts']}",
        ),
        signature=q["sig"],
    )
    assert recovered.lower() == _consumer_addr().lower()


@pytest.mark.asyncio
async def test_fetch_pending_empty(client):
    transport, patched = _install_transport(lambda r: (200, _pending_payload([])))
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.fetch_pending()
    assert result["receipts"] == []


# ── submit_signatures ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_signatures_forwards_body(client):
    captured = {}
    def handler(req):
        body = json.loads(req.content)
        captured["body"] = body
        return 200, {"accepted": [body["signatures"][0]["request_uuid"]],
                     "rejected": []}

    transport, patched = _install_transport(handler)
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.submit_signatures([
            {"request_uuid": "u1", "signature": "0xdead"},
        ])
    assert result["accepted"] == ["u1"]
    assert captured["body"]["address"] == _consumer_addr()
    assert captured["body"]["signatures"][0]["request_uuid"] == "u1"
    # Outer auth included
    assert captured["body"]["sig"].startswith("0x")


@pytest.mark.asyncio
async def test_submit_signatures_empty_skips_http(client):
    transport, patched = _install_transport(lambda r: (200, {}))
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.submit_signatures([])
    assert result == {"accepted": [], "rejected": []}
    # No network call
    assert transport.calls == []


# ── sync_receipts (end-to-end) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_receipts_signs_and_submits(client):
    row1 = _receipt_row(data_amount=1024, total_price=100)
    row2 = _receipt_row(data_amount=2048, total_price=200)

    submitted = {}

    def handler(req):
        if req.url.path == "/leg1/pending":
            return 200, _pending_payload([row1, row2])
        assert req.url.path == "/leg1/sign"
        body = json.loads(req.content)
        submitted["payload"] = body
        # Verify each signature recovers to consumer
        for sub in body["signatures"]:
            r_row = row1 if sub["request_uuid"] == row1["request_uuid"] else row2
            receipt = Receipt(
                client_address=r_row["client_address"],
                node_address=r_row["node_address"],
                request_uuid=r_row["request_uuid"],
                data_amount=int(r_row["data_amount"]),
                total_price=int(r_row["total_price"]),
            )
            recovered = recover_receipt_signer(
                receipt, sub["signature"], DOMAIN,
            )
            assert recovered.lower() == _consumer_addr().lower()
        return 200, {
            "accepted": [s["request_uuid"] for s in body["signatures"]],
            "rejected": [],
        }

    transport, patched = _install_transport(handler)
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.sync_receipts()

    assert result["pending_count"] == 2
    assert len(result["accepted"]) == 2
    assert result["rejected"] == []


@pytest.mark.asyncio
async def test_sync_receipts_noop_when_nothing_pending(client):
    def handler(req):
        assert req.url.path == "/leg1/pending"
        return 200, _pending_payload([])

    transport, patched = _install_transport(handler)
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.sync_receipts()

    assert result == {"accepted": [], "rejected": [], "pending_count": 0}
    # Only the fetch was called, no submit.
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_sync_receipts_handles_gateway_partial_rejection(client):
    row_ok = _receipt_row()
    row_stale = _receipt_row()

    def handler(req):
        if req.url.path == "/leg1/pending":
            return 200, _pending_payload([row_ok, row_stale])
        return 200, {
            "accepted": [row_ok["request_uuid"]],
            "rejected": [{
                "request_uuid": row_stale["request_uuid"],
                "reason": "not_pending",
            }],
        }

    transport, patched = _install_transport(handler)
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.sync_receipts()

    assert result["accepted"] == [row_ok["request_uuid"]]
    assert result["rejected"][0]["reason"] == "not_pending"


@pytest.mark.asyncio
async def test_http_error_propagates(client):
    def handler(req):
        return 500, {"detail": "boom"}

    transport, patched = _install_transport(handler)
    with patch.object(httpx.AsyncClient, "__init__", patched):
        with pytest.raises(httpx.HTTPStatusError):
            await client.fetch_pending()


# ── SpaceRouterSPACE.sync_receipts convenience ────────────────────────


@pytest.mark.asyncio
async def test_spacerouter_space_sync_receipts():
    from spacerouter.payment import SpaceRouterSPACE

    sr = SpaceRouterSPACE(
        gateway_url="https://gateway.example",
        proxy_url="https://gateway.example:8080",
        private_key=CONSUMER_KEY,
        chain_id=102031,
        escrow_contract="0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
    )

    row = _receipt_row()
    def handler(req):
        if req.url.path == "/leg1/pending":
            return 200, _pending_payload([row])
        body = json.loads(req.content)
        return 200, {
            "accepted": [body["signatures"][0]["request_uuid"]],
            "rejected": [],
        }

    transport, patched = _install_transport(handler)
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await sr.sync_receipts()

    assert result["accepted"] == [row["request_uuid"]]
    assert result["pending_count"] == 1
