"""Tenacity retry coverage for the Leg 1 settlement client.

Per v1.5 protocol §9: HTTP 5xx and transport errors must be retried
with bounded exponential backoff (default 3 attempts, 200ms / 1s / 5s),
surfacing the response body verbatim on final failure.

Uses ``httpx.MockTransport`` to script 503/503/200 sequences. We monkey-
patch ``asyncio.sleep`` to a no-op so the test runs fast without
disabling tenacity's retry logic itself.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from spacerouter.payment.consumer_settlement import ConsumerSettlementClient


CONSUMER_KEY = (
    "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937"
)


class _SeqMockTransport(httpx.AsyncBaseTransport):
    """Returns canned (status, body) tuples in order; counts attempts.

    Lets us assert exactly how many times tenacity retried.
    """

    def __init__(self, responses: list[tuple[int, dict]]):
        self._responses = list(responses)
        self.calls: list[httpx.Request] = []

    async def handle_async_request(self, request):
        self.calls.append(request)
        if not self._responses:
            raise AssertionError("transport ran out of canned responses")
        status, body = self._responses.pop(0)
        return httpx.Response(
            status_code=status,
            content=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
            request=request,
        )


def _install_transport(transport: _SeqMockTransport):
    """Monkeypatch httpx.AsyncClient to inject our transport."""
    orig = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("verify", None)
        orig(self, *args, **kwargs)

    return patched


@pytest.fixture
def fast_sleep():
    """Skip tenacity's real sleep so retries run instantly."""
    async def _noop(_):
        return None
    with patch.object(asyncio, "sleep", _noop):
        yield


@pytest.fixture
def client():
    return ConsumerSettlementClient(
        gateway_url="https://gateway.example", private_key=CONSUMER_KEY,
    )


def _pending_payload() -> dict:
    return {
        "receipts": [],
        "domain": {
            "name": "TokenPaymentEscrow",
            "version": "1",
            "chainId": 102031,
            "verifyingContract": "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
        },
    }


# ── fetch_pending: retry on 5xx ───────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_pending_retries_503_then_succeeds(client, fast_sleep):
    transport = _SeqMockTransport([
        (503, {"detail": "upstream busy"}),
        (503, {"detail": "still busy"}),
        (200, _pending_payload()),
    ])
    with patch.object(httpx.AsyncClient, "__init__", _install_transport(transport)):
        result = await client.fetch_pending()

    assert len(transport.calls) == 3, "expected exactly 3 attempts"
    assert result["receipts"] == []


@pytest.mark.asyncio
async def test_fetch_pending_gives_up_after_3_5xx_with_verbatim_body(
    client, fast_sleep,
):
    transport = _SeqMockTransport([
        (503, {"detail": "boom-1"}),
        (503, {"detail": "boom-2"}),
        (503, {"detail": "boom-final"}),
    ])
    with patch.object(httpx.AsyncClient, "__init__", _install_transport(transport)):
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            await client.fetch_pending()

    assert len(transport.calls) == 3
    # Verbatim body is reachable from the raised exception.
    assert excinfo.value.response.status_code == 503
    assert "boom-final" in excinfo.value.response.text


# ── submit_signatures: retry on 5xx ───────────────────────────────────


@pytest.mark.asyncio
async def test_submit_signatures_retries_503_then_succeeds(client, fast_sleep):
    transport = _SeqMockTransport([
        (503, {"detail": "scaling up"}),
        (503, {"detail": "scaling up"}),
        (200, {"accepted": ["u1"], "rejected": []}),
    ])
    with patch.object(httpx.AsyncClient, "__init__", _install_transport(transport)):
        result = await client.submit_signatures([
            {"request_uuid": "u1", "signature": "0xdead"},
        ])

    assert len(transport.calls) == 3
    assert result["accepted"] == ["u1"]


@pytest.mark.asyncio
async def test_submit_signatures_retries_on_transport_error(
    client, fast_sleep,
):
    """httpx.TransportError (network blip) must trigger retry too."""

    class _FlakyTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.attempts = 0

        async def handle_async_request(self, request):
            self.attempts += 1
            if self.attempts < 3:
                raise httpx.ConnectError("connection refused", request=request)
            return httpx.Response(
                status_code=200,
                content=json.dumps(
                    {"accepted": ["u1"], "rejected": []},
                ).encode(),
                headers={"content-type": "application/json"},
                request=request,
            )

    transport = _FlakyTransport()
    orig = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("verify", None)
        orig(self, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "__init__", patched):
        result = await client.submit_signatures([
            {"request_uuid": "u1", "signature": "0xdead"},
        ])
    assert transport.attempts == 3
    assert result["accepted"] == ["u1"]
