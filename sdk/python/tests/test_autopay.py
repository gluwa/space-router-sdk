"""Auto-pay integration: SpaceRouter ↔ SpaceRouterSPACE wiring.

Verifies the v1.5 consumer SDK auto-pay path:
  1. payment auth headers are injected on every request,
  2. a fresh challenge is fetched per call (no reuse),
  3. ``auto_settle=True`` triggers ``payment.sync_receipts()``,
  4. the legacy api-key-only path is unchanged when no payment is set.

Network calls are mocked via a small in-memory ``SpaceRouterSPACE``
double — we don't exercise httpx for the payment side here, that's
covered by ``test_consumer_settlement*``. We only assert the orchestration
in ``client.request``.
"""

from __future__ import annotations

import pytest
import respx
import httpx

from spacerouter import (
    AsyncSpaceRouter,
    SpaceRouter,
    SpaceRouterSPACE,
)


# ── Fakes ──────────────────────────────────────────────────────────────


class _FakePayment:
    """Stand-in for SpaceRouterSPACE that records orchestration calls.

    Implements the exact surface SpaceRouter.request needs:
    ``request_challenge`` (async), ``build_auth_headers`` (sync),
    ``sync_receipts`` (async). Each challenge is unique so the test can
    prove a fresh one is fetched per request.
    """

    def __init__(self) -> None:
        self.challenge_calls = 0
        self.last_challenge: str | None = None
        self.sync_calls = 0

    async def request_challenge(self) -> str:
        self.challenge_calls += 1
        c = f"challenge-{self.challenge_calls}"
        self.last_challenge = c
        return c

    def build_auth_headers(self, challenge: str) -> dict[str, str]:
        return {
            "X-SpaceRouter-Payment-Address": "0xabc",
            "X-SpaceRouter-Identity-Address": "0xabc",
            "X-SpaceRouter-Challenge": challenge,
            "X-SpaceRouter-Challenge-Signature": "0xsig",
        }

    async def sync_receipts(self) -> dict:
        self.sync_calls += 1
        return {"accepted": [], "rejected": [], "pending_count": 0}


# ── Sync client tests ─────────────────────────────────────────────────


class TestSpaceRouterAutoPay:
    @respx.mock
    def test_payment_headers_injected(self):
        """When payment is set, CONNECT carries v1.5 auth headers."""
        route = respx.get("http://example.com/").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        payment = _FakePayment()
        with SpaceRouter("sr_live_test", payment=payment) as client:
            resp = client.get("http://example.com/")
            assert resp.status_code == 200

        assert route.called
        sent_headers = route.calls.last.request.headers
        assert sent_headers["X-SpaceRouter-Payment-Address"] == "0xabc"
        assert sent_headers["X-SpaceRouter-Challenge"] == "challenge-1"
        assert sent_headers["X-SpaceRouter-Challenge-Signature"] == "0xsig"

    @respx.mock
    def test_fresh_challenge_per_call(self):
        """Each request fetches a new challenge — never cached."""
        respx.get("http://example.com/").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        payment = _FakePayment()
        with SpaceRouter("sr_live_test", payment=payment) as client:
            client.get("http://example.com/")
            client.get("http://example.com/")
            client.get("http://example.com/")

        assert payment.challenge_calls == 3
        assert payment.last_challenge == "challenge-3"

    @respx.mock
    def test_auto_settle_invokes_sync_receipts(self):
        """auto_settle=True runs sync_receipts after each successful call."""
        respx.get("http://example.com/").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        payment = _FakePayment()
        with SpaceRouter(
            "sr_live_test", payment=payment, auto_settle=True,
        ) as client:
            client.get("http://example.com/")
            client.get("http://example.com/")

        assert payment.sync_calls == 2

    @respx.mock
    def test_no_payment_uses_apikey_path_unchanged(self):
        """Legacy path: api-key only, no payment headers anywhere."""
        route = respx.get("http://example.com/").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        with SpaceRouter("sr_live_test") as client:
            resp = client.get("http://example.com/")
            assert resp.status_code == 200

        sent = route.calls.last.request.headers
        for h in (
            "X-SpaceRouter-Payment-Address",
            "X-SpaceRouter-Identity-Address",
            "X-SpaceRouter-Challenge",
            "X-SpaceRouter-Challenge-Signature",
        ):
            assert h not in sent, f"unexpected v1.5 header on api-key path: {h}"

    @respx.mock
    def test_user_headers_preserved_payment_takes_precedence(self):
        """User headers go through; payment headers win on collision."""
        route = respx.get("http://example.com/").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        payment = _FakePayment()
        with SpaceRouter("sr_live_test", payment=payment) as client:
            client.get(
                "http://example.com/",
                headers={
                    "X-Custom": "kept",
                    # Lowercase to test case-insensitive collision logic.
                    "x-spacerouter-challenge": "stale-from-caller",
                },
            )

        sent = route.calls.last.request.headers
        assert sent["X-Custom"] == "kept"
        # Payment-fetched challenge wins, not the stale one.
        assert sent["X-SpaceRouter-Challenge"] == "challenge-1"

    @respx.mock
    def test_auto_settle_swallows_failure_by_default(self, caplog):
        """sync_receipts errors must not break the request unless strict."""
        respx.get("http://example.com/").mock(
            return_value=httpx.Response(200, text="ok"),
        )

        class _Boom(_FakePayment):
            async def sync_receipts(self):
                raise RuntimeError("settlement broker unreachable")

        payment = _Boom()
        with SpaceRouter(
            "sr_live_test", payment=payment, auto_settle=True,
        ) as client:
            resp = client.get("http://example.com/")
            assert resp.status_code == 200  # request still succeeds


# ── Async client smoke ────────────────────────────────────────────────


class TestAsyncSpaceRouterAutoPay:
    @pytest.mark.asyncio
    @respx.mock
    async def test_async_auto_settle_invokes_sync_receipts(self):
        respx.get("http://example.com/").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        payment = _FakePayment()
        async with AsyncSpaceRouter(
            "sr_live_test", payment=payment, auto_settle=True,
        ) as client:
            await client.get("http://example.com/")
            await client.get("http://example.com/")

        assert payment.challenge_calls == 2
        assert payment.sync_calls == 2


# ── Type sanity: real SpaceRouterSPACE constructible alongside ────────


def test_spacerouter_space_compatible_for_typing():
    """Smoke: SpaceRouter accepts a real SpaceRouterSPACE instance."""
    sr_space = SpaceRouterSPACE(
        gateway_url="https://gateway.example",
        proxy_url="https://gateway.example:8080",
        private_key="0x" + "11" * 32,
        chain_id=102031,
        escrow_contract="0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
    )
    # Just constructs; doesn't run any network.
    client = SpaceRouter("sr_live_test", payment=sr_space, auto_settle=False)
    assert client._payment is sr_space
    client.close()
