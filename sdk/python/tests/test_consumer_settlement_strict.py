"""Strict-mode SettlementRejected tests.

Per v1.5 protocol §9: ``POST /leg1/sign`` returning a non-empty
``rejected`` list is normal operating output, NOT a transport error.
SDKs MUST surface every reason and MUST NOT raise unless the caller
opts in via ``strict=True``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from spacerouter import SettlementRejected
from spacerouter.payment.consumer_settlement import ConsumerSettlementClient


CONSUMER_KEY = (
    "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937"
)


def _install_handler(handler):
    transport_calls: list = []

    class _T(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            transport_calls.append(request)
            status, body = handler(request)
            return httpx.Response(
                status_code=status,
                content=json.dumps(body).encode(),
                headers={"content-type": "application/json"},
                request=request,
            )

    transport = _T()
    orig = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("verify", None)
        orig(self, *args, **kwargs)

    return transport_calls, patched


@pytest.fixture
def client():
    return ConsumerSettlementClient(
        gateway_url="https://gateway.example", private_key=CONSUMER_KEY,
    )


_REJECTED_BODY = {
    "accepted": [],
    "rejected": [
        {"request_uuid": "u1", "reason": "eip712_signer_mismatch"},
    ],
}


@pytest.mark.asyncio
async def test_submit_signatures_strict_raises_on_rejection(client):
    """strict=True + non-empty rejected => SettlementRejected."""
    _, patched = _install_handler(lambda r: (200, _REJECTED_BODY))
    with patch.object(httpx.AsyncClient, "__init__", patched):
        with pytest.raises(SettlementRejected) as excinfo:
            await client.submit_signatures(
                [{"request_uuid": "u1", "signature": "0xdead"}],
                strict=True,
            )
    # Reasons preserved verbatim from the gateway.
    assert excinfo.value.reasons == _REJECTED_BODY["rejected"]
    assert excinfo.value.reasons[0]["reason"] == "eip712_signer_mismatch"


@pytest.mark.asyncio
async def test_submit_signatures_default_swallows_rejection(client):
    """strict defaults to False — caller inspects result dict."""
    _, patched = _install_handler(lambda r: (200, _REJECTED_BODY))
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.submit_signatures(
            [{"request_uuid": "u1", "signature": "0xdead"}],
        )
    assert result["rejected"][0]["reason"] == "eip712_signer_mismatch"
    assert result["accepted"] == []


@pytest.mark.asyncio
async def test_submit_signatures_strict_with_no_rejection_returns_normally(
    client,
):
    """strict=True is a no-op when nothing was rejected."""
    body = {"accepted": ["u1"], "rejected": []}
    _, patched = _install_handler(lambda r: (200, body))
    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.submit_signatures(
            [{"request_uuid": "u1", "signature": "0xdead"}],
            strict=True,
        )
    assert result == body


@pytest.mark.asyncio
async def test_sync_receipts_propagates_strict_to_submit(client):
    """sync_receipts(strict=True) must raise when gateway rejects."""
    pending_payload = {
        "receipts": [
            {
                "request_uuid": "u1",
                "client_address": "0x61F5B13A42016D94AdEaC2857f77cc7cd9f0e11C",
                "node_address": "0x" + "bb" * 32,
                "data_amount": 1024,
                "total_price": "100",
                "tunnel_request_id": "tun-1",
                "created_at": "2026-04-21T10:00:00+00:00",
            }
        ],
        "domain": {
            "name": "TokenPaymentEscrow",
            "version": "1",
            "chainId": 102031,
            "verifyingContract": "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
        },
    }

    def handler(req):
        if req.url.path == "/leg1/pending":
            return 200, pending_payload
        return 200, _REJECTED_BODY

    _, patched = _install_handler(handler)
    with patch.object(httpx.AsyncClient, "__init__", patched):
        with pytest.raises(SettlementRejected):
            await client.sync_receipts(strict=True)
