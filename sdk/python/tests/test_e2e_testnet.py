"""End-to-end pytest suite for the v1.5 escrow consumer flow.

Targets the testnet gateway at
``https://spacerouter-proxy-gateway-test.fly.dev`` and the
``TokenPaymentEscrow`` contract on Creditcoin testnet
(chain id 102031). The whole module is gated on environment variables so
unconfigured runners (CI, local dev without a funded wallet) skip
cleanly without a single test failure.

Required env vars (all must be set or the module is skipped):

  SR_TESTNET_PRIVATE_KEY     funded consumer wallet (hex, 0x-prefixed ok)

Optional env vars (defaults shown):

  SR_TESTNET_GATEWAY         https://spacerouter-proxy-gateway-test.fly.dev
  SR_TESTNET_GATEWAY_MGMT    same host (used for /leg1/* and /auth/* routes)
  SR_ESCROW_CONTRACT_ADDRESS 0xC5740e4e9175301a24FB6d22bA184b8ec0762852
  SR_ESCROW_CHAIN_RPC        https://rpc.cc3-testnet.creditcoin.network
  SR_ESCROW_TOKEN_ADDRESS    0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA

Run:

  .venv/bin/pytest -x sdk/python/tests/test_e2e_testnet.py -v

Expected wall-clock: ~2-3 minutes. See ``E2E.md`` next to this file for the
full operator runbook.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import pytest

logger = logging.getLogger(__name__)


# ── Env wiring ────────────────────────────────────────────────────────


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val


PRIVATE_KEY = _env("SR_TESTNET_PRIVATE_KEY")
GATEWAY = _env(
    "SR_TESTNET_GATEWAY", "https://spacerouter-proxy-gateway-test.fly.dev"
)
GATEWAY_MGMT = _env("SR_TESTNET_GATEWAY_MGMT", GATEWAY)
ESCROW_ADDRESS = _env(
    "SR_ESCROW_CONTRACT_ADDRESS",
    "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
)
RPC_URL = _env(
    "SR_ESCROW_CHAIN_RPC", "https://rpc.cc3-testnet.creditcoin.network",
)
TOKEN_ADDRESS = _env(
    "SR_ESCROW_TOKEN_ADDRESS",
    "0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA",
)

# Per-run prefix. Lets a maintainer grep for "e2e-py-" in the gateway DB
# and bulk-purge stale receipts from a flaky run.
REQUEST_UUID_PREFIX = f"e2e-py-{int(time.time())}-"

# Skip marker for the live tests when the consumer wallet is missing. We
# do NOT skip on missing optional vars because they all have sensible
# testnet defaults. Applied per-test rather than module-wide so the
# canonical EIP-712 vector at the bottom can still run standalone.
_REQUIRES_LIVE = pytest.mark.skipif(
    not PRIVATE_KEY,
    reason=(
        "SR_TESTNET_PRIVATE_KEY is not set — see sdk/python/tests/E2E.md"
    ),
)


# ── Shared session state ──────────────────────────────────────────────
#
# Tests in this module are intentionally ordered: each one is independent
# (idempotent, can be run alone) but later tests can opportunistically
# reuse state captured by earlier ones (e.g. a fresh request_uuid from the
# paid-request round-trip is the easiest way to assert ``isNonceUsed``
# returns True).
SESSION_STATE: dict[str, Any] = {}


# ── Lazy fixtures (only built when env vars are set) ──────────────────


@pytest.fixture(scope="module")
def consumer_address() -> str:
    from eth_account import Account
    return Account.from_key(PRIVATE_KEY).address


@pytest.fixture(scope="module")
def escrow():
    """A read+write EscrowClient bound to the test wallet."""
    from spacerouter.escrow import EscrowClient
    return EscrowClient(
        rpc_url=RPC_URL,
        contract_address=ESCROW_ADDRESS,
        private_key=PRIVATE_KEY,
    )


@pytest.fixture(scope="module")
def space_client():
    """High-level Consumer client for the proxy + Leg 1 settlement."""
    from spacerouter.payment import SpaceRouterSPACE
    return SpaceRouterSPACE(
        gateway_url=GATEWAY_MGMT,
        proxy_url=GATEWAY,
        private_key=PRIVATE_KEY,
        chain_id=102031,
        escrow_contract=ESCROW_ADDRESS,
    )


# ── Helpers ───────────────────────────────────────────────────────────


def _poll(predicate, *, timeout: float, interval: float = 2.0, what: str):
    """Poll ``predicate`` until truthy or timeout. Returns the last value.

    Raises ``pytest.fail.Exception`` on timeout — the SDK chain RPC has
    flaky moments on testnet so the message includes ``what`` for
    triage."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    pytest.fail(
        f"Timeout after {timeout:.0f}s waiting for: {what}. Last value: {last!r}"
    )


def _gen_uuid() -> str:
    """Per-test request UUID. Prefixed for manual cleanup."""
    return REQUEST_UUID_PREFIX + uuid.uuid4().hex


# ── 1. Balance reads ──────────────────────────────────────────────────


@_REQUIRES_LIVE
def test_balance_reads(escrow, consumer_address):
    """Sanity: both balance reads return without raising for a fresh wallet.

    Asserts the EscrowClient successfully connects to the RPC + contract
    pair. Returning zero is a valid answer (not a failure)."""
    escrow_balance = escrow.balance(consumer_address)
    token_balance = escrow.token_balance(consumer_address)
    assert isinstance(escrow_balance, int) and escrow_balance >= 0
    assert isinstance(token_balance, int) and token_balance >= 0
    SESSION_STATE["initial_escrow_balance"] = escrow_balance
    SESSION_STATE["initial_token_balance"] = token_balance
    logger.info(
        "Wallet %s: escrow=%d wei, token=%d wei",
        consumer_address, escrow_balance, token_balance,
    )


# ── 2. Deposit round-trip ─────────────────────────────────────────────


ONE_ETHER = 10**18


@_REQUIRES_LIVE
def test_deposit_round_trip(escrow, consumer_address):
    """Deposit 1 SPACE if the wallet has it, then assert the escrow grew.

    SKIPs cleanly when the wallet is below 1 SPACE (we don't want a
    misconfigured wallet to take down the rest of the suite — the read
    tests above remain useful)."""
    initial_escrow = escrow.balance(consumer_address)
    token_balance = escrow.token_balance(consumer_address)

    if token_balance < ONE_ETHER:
        pytest.skip(
            f"Wallet {consumer_address} token balance {token_balance} < 1 ether — "
            "fund with Mock SPACE before running this test (see E2E.md)."
        )

    tx_hash = escrow.deposit(ONE_ETHER)
    logger.info("deposit tx=%s", tx_hash)

    new_balance = _poll(
        lambda: (
            v if (v := escrow.balance(consumer_address)) >= initial_escrow + ONE_ETHER
            else None
        ),
        timeout=120.0,
        interval=3.0,
        what=f"escrow balance to grow by {ONE_ETHER} wei after deposit",
    )
    assert new_balance == initial_escrow + ONE_ETHER, (
        f"Expected escrow balance {initial_escrow + ONE_ETHER}, got {new_balance}"
    )


# ── 3. Paid request round-trip ────────────────────────────────────────


PROXY_TARGET = os.environ.get(
    "SR_TESTNET_PROXY_TARGET",
    "https://api.cc3-testnet.creditcoin.network/health",
)


def _fetch_challenge(gateway_mgmt: str) -> str:
    import httpx
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{gateway_mgmt.rstrip('/')}/auth/challenge")
        r.raise_for_status()
        return r.json()["challenge"]


def _make_paid_request(consumer, target: str) -> int:
    """Send one CONNECT-tunnelled GET via the gateway proxy.

    Returns the HTTP status code. Failures hit the gateway are surfaced
    verbatim — they are still a useful signal because the gateway logs
    Leg 1 receipts on every accepted CONNECT, even for non-200 upstream
    responses."""
    import httpx
    challenge = _fetch_challenge(consumer.gateway_url)
    headers = consumer.build_auth_headers(challenge)
    proxy_url = consumer.proxy_url

    with httpx.Client(
        proxy=proxy_url, timeout=30.0,
        # The gateway tunnels the tunnelled request unchanged; the auth
        # headers MUST go on the CONNECT request itself, not the inner
        # GET — see §4 of the protocol doc.
        headers=headers,
    ) as client:
        # ``trust_env=False`` would be cleaner but httpx 0.28 doesn't pop
        # ``HTTP_PROXY`` consistently for proxies; we rely on the explicit
        # ``proxy=`` kwarg to win.
        r = client.get(target)
        return r.status_code


@_REQUIRES_LIVE
@pytest.mark.asyncio
async def test_paid_request_round_trip(space_client, consumer_address):
    """One paid GET → at least one Leg 1 receipt accepted by the gateway.

    Doesn't assert on the upstream response (we route to a public
    testnet health endpoint that may or may not be 200 in steady state) —
    what matters is that the gateway minted a Leg 1 receipt and we
    countersigned it via ``sync_receipts``."""
    try:
        status = _make_paid_request(space_client, PROXY_TARGET)
    except Exception as exc:
        pytest.fail(
            f"Paid CONNECT through {space_client.proxy_url} → {PROXY_TARGET} "
            f"failed: {exc!r}. Check that the wallet has escrow balance "
            "(test_deposit_round_trip should run first) and that the gateway "
            "is reachable."
        )
    logger.info("Paid request to %s → %d", PROXY_TARGET, status)

    # Give the gateway a moment to flush the receipt to its DB.
    time.sleep(2.0)

    # sync_receipts polls /leg1/pending, signs, and POSTs to /leg1/sign.
    # Because the gateway is the source of truth for ``request_uuid``,
    # we don't pre-pick one; we capture whatever it minted.
    result: dict[str, Any] = {}
    deadline = time.time() + 60.0
    while time.time() < deadline:
        result = await space_client.sync_receipts()
        if result.get("accepted"):
            break
        time.sleep(3.0)

    assert result.get("accepted"), (
        f"sync_receipts saw no accepted receipts within 60s: "
        f"pending_count={result.get('pending_count')}, "
        f"rejected={result.get('rejected')}"
    )
    accepted_uuid = result["accepted"][0]
    SESSION_STATE["paid_request_uuid"] = accepted_uuid
    logger.info("Settled receipt uuid=%s", accepted_uuid)


# ── 4. usedNonces after settle ────────────────────────────────────────


@_REQUIRES_LIVE
def test_isnonce_used_after_settle(escrow, consumer_address):
    """After Leg 1 settles, the gateway eventually claims via ``claimBatch``.

    This test is timing-dependent: claimBatch runs on the gateway's batch
    cadence (~minutes on testnet), so we poll for up to 120s. If still
    unclaimed, the test SKIPs rather than fails — settlement on-chain is
    a Leg 2 concern owned by the gateway, not the SDK."""
    request_uuid = SESSION_STATE.get("paid_request_uuid")
    if not request_uuid:
        pytest.skip(
            "test_paid_request_round_trip did not record a request_uuid — "
            "this test depends on a successful Leg 1 settlement first."
        )

    deadline = time.time() + 120.0
    used = False
    while time.time() < deadline:
        used = escrow.is_nonce_used(consumer_address, request_uuid)
        if used:
            break
        time.sleep(5.0)

    if not used:
        pytest.skip(
            f"Receipt {request_uuid} settled off-chain but gateway has not yet "
            "submitted claimBatch on-chain (testnet cadence ~minutes). Re-run "
            "in 10 minutes to verify the on-chain leg."
        )
    assert used


# ── 5. Withdrawal initiate + cancel ──────────────────────────────────


def _initiate_withdrawal_zero(escrow_client) -> str:
    """Bypass the SDK's ``amount > 0`` guard for the zero-amount no-op.

    The SDK preflights ``amount > 0`` to protect callers from typos, but
    the ``TokenPaymentEscrow`` contract itself accepts 0 (it just records
    a withdrawal request with amount=0). For a non-destructive E2E we
    want exactly that no-op so the test doesn't disturb a real escrow
    balance.

    Uses the EscrowClient's underlying contract object directly. Falls
    back to ``initiate_withdrawal(1)`` if the contract surprisingly
    rejects 0 — the test then cancels regardless."""
    contract = escrow_client._contract  # noqa: SLF001 — internal but stable
    try:
        return escrow_client._send_tx(  # noqa: SLF001
            contract.functions.initiateWithdrawal(0), gas=150_000,
        )
    except Exception:
        return escrow_client._send_tx(  # noqa: SLF001
            contract.functions.initiateWithdrawal(1), gas=150_000,
        )


@_REQUIRES_LIVE
def test_withdrawal_initiate_then_cancel(escrow, consumer_address):
    """Round-trip: initiate a (zero-amount) withdrawal, then cancel it.

    Confirms the contract surface end-to-end without permanently moving
    funds. If the wallet already has a pending withdrawal from a previous
    aborted test run, we cancel it first to start clean."""
    # Clean any pre-existing request from a flaky prior run.
    amount, _ready_at, exists = escrow.withdrawal_request(consumer_address)
    if exists:
        logger.info(
            "Pre-existing withdrawal request (amount=%d) — cancelling first",
            amount,
        )
        escrow.cancel_withdrawal()
        _poll(
            lambda: (
                True if not escrow.withdrawal_request(consumer_address)[2]
                else None
            ),
            timeout=60.0, interval=2.0,
            what="pre-existing withdrawal request to clear",
        )

    tx_hash = _initiate_withdrawal_zero(escrow)
    logger.info("initiateWithdrawal tx=%s", tx_hash)

    _poll(
        lambda: (
            escrow.withdrawal_request(consumer_address)
            if escrow.withdrawal_request(consumer_address)[2]
            else None
        ),
        timeout=60.0, interval=2.0,
        what="withdrawal request to appear after initiate",
    )
    _amount, _ready_at, exists = escrow.withdrawal_request(consumer_address)
    assert exists is True

    cancel_tx = escrow.cancel_withdrawal()
    logger.info("cancelWithdrawal tx=%s", cancel_tx)

    _poll(
        lambda: (
            True if not escrow.withdrawal_request(consumer_address)[2]
            else None
        ),
        timeout=60.0, interval=2.0,
        what="withdrawal request to clear after cancel",
    )
    _amount, _ready_at, still_exists = escrow.withdrawal_request(
        consumer_address,
    )
    assert still_exists is False


# ── 6. Canonical EIP-712 protocol vector ─────────────────────────────
#
# Track A also owns this vector; we duplicate it here so the E2E suite
# can run standalone (without depending on the helper-only test module
# above) and so a maintainer recompiling the live tests gets a fast
# pre-flight signal that the EIP-712 stack still produces the expected
# byte string.

CANONICAL_KEY = (
    "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937"
)
CANONICAL_ADDRESS = "0x61F5B13A42016D94AdEaC2857f77cc7cd9f0e11C"
CANONICAL_SIGNATURE = (
    "0x15cbab3e32932fdfc01ebfb712b34ef1970f9b7b6e08318aea414ca1dbd4a2bf"
    "04d5812dda908013e42091ae473667dfbf6110432e1f4e3ee7b9543916c61dd41c"
)


def test_protocol_vector():
    """§7 of v1.5-consumer-protocol.md — pinned cross-stack vector."""
    from spacerouter.payment.eip712 import (
        EIP712Domain,
        Receipt,
        recover_receipt_signer,
        sign_receipt,
    )

    domain = EIP712Domain(
        name="TokenPaymentEscrow",
        version="1",
        chain_id=102031,
        verifying_contract="0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
    )
    receipt = Receipt(
        client_address=CANONICAL_ADDRESS,
        node_address=(
            "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789"
        ),
        request_uuid="00000000-0000-0000-0000-000000000001",
        data_amount=1024,
        total_price=1000000000000000,
    )
    sig = sign_receipt(CANONICAL_KEY, receipt, domain)
    assert sig.lower() == CANONICAL_SIGNATURE.lower()

    recovered = recover_receipt_signer(receipt, sig, domain)
    assert recovered.lower() == CANONICAL_ADDRESS.lower()
