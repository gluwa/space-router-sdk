"""Unit tests for the helpers used by ``test_e2e_testnet.py``.

The live E2E module is gated behind several env vars and skipped wholesale
when any are missing. To keep coverage on the support code that runs *before*
those env vars are checked (env parsing, request_uuid construction, etc.),
this module exercises the helpers in isolation against mocked httpx + web3
surfaces.

Run with:

    .venv/bin/pytest -x sdk/python/tests/test_e2e_helpers.py -v
"""

from __future__ import annotations

import time

import pytest

from spacerouter.payment.eip712 import (
    EIP712Domain,
    Receipt,
    address_to_bytes32,
    recover_receipt_signer,
    sign_receipt,
)


# ── Env helpers ───────────────────────────────────────────────────────


def _env_setup(monkeypatch, **overrides):
    """Set the e2e env vars to known values. Pass ``None`` to clear."""
    base = {
        "SR_TESTNET_PRIVATE_KEY": (
            "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937"
        ),
        "SR_TESTNET_GATEWAY": "https://example.invalid",
        "SR_TESTNET_GATEWAY_MGMT": "https://example.invalid",
        "SR_ESCROW_CONTRACT_ADDRESS": (
            "0xC5740e4e9175301a24FB6d22bA184b8ec0762852"
        ),
        "SR_ESCROW_CHAIN_RPC": "https://rpc.invalid",
        "SR_ESCROW_TOKEN_ADDRESS": (
            "0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA"
        ),
    }
    base.update(overrides)
    for k, v in base.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def _reload_e2e_module():
    """Load ``test_e2e_testnet`` afresh so it picks up the current env.

    Uses ``importlib.util.spec_from_file_location`` rather than a regular
    ``import`` so we don't depend on pytest's collector having added the
    tests directory to ``sys.path`` — the same trick lets every helper
    test see freshly-evaluated module-level constants."""
    import importlib.util
    import pathlib
    import sys

    here = pathlib.Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "_e2e_under_test", here / "test_e2e_testnet.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Cache under a private name so reloading just re-runs the file.
    sys.modules["_e2e_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_e2e_module_import_skips_cleanly_without_required_env(monkeypatch):
    """If ``SR_TESTNET_PRIVATE_KEY`` is missing, the module-level skip fires
    on collection — the import itself MUST succeed so pytest can report the
    skip reason cleanly rather than crashing."""
    _env_setup(monkeypatch, SR_TESTNET_PRIVATE_KEY=None)
    mod = _reload_e2e_module()
    # The skip marker is module-level; the helpers import without raising.
    assert hasattr(mod, "REQUEST_UUID_PREFIX")
    assert mod.PRIVATE_KEY is None


def test_request_uuid_prefix_is_per_session(monkeypatch):
    _env_setup(monkeypatch)
    mod = _reload_e2e_module()
    # The prefix encodes a unix timestamp so old runs don't collide on
    # gateway state if the same wallet is reused.
    prefix = mod.REQUEST_UUID_PREFIX
    assert prefix.startswith("e2e-py-"), prefix
    ts_str = prefix.removeprefix("e2e-py-").rstrip("-")
    ts = int(ts_str)
    # Within a few seconds of "now"
    assert abs(ts - int(time.time())) < 5


def test_env_defaults_apply(monkeypatch):
    """Optional env vars use the testnet defaults when unset."""
    _env_setup(
        monkeypatch,
        SR_TESTNET_GATEWAY=None,
        SR_TESTNET_GATEWAY_MGMT=None,
        SR_ESCROW_CONTRACT_ADDRESS=None,
        SR_ESCROW_CHAIN_RPC=None,
        SR_ESCROW_TOKEN_ADDRESS=None,
    )
    mod = _reload_e2e_module()
    assert mod.GATEWAY == "https://spacerouter-proxy-gateway-test.fly.dev"
    assert mod.GATEWAY_MGMT == mod.GATEWAY
    assert mod.ESCROW_ADDRESS == (
        "0xC5740e4e9175301a24FB6d22bA184b8ec0762852"
    )
    assert mod.RPC_URL == "https://rpc.cc3-testnet.creditcoin.network"
    assert mod.TOKEN_ADDRESS == (
        "0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA"
    )


# ── Canonical EIP-712 protocol vector ────────────────────────────────


CANONICAL_KEY = (
    "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937"
)
CANONICAL_ADDRESS = "0x61F5B13A42016D94AdEaC2857f77cc7cd9f0e11C"
CANONICAL_DOMAIN = EIP712Domain(
    name="TokenPaymentEscrow",
    version="1",
    chain_id=102031,
    verifying_contract="0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
)
CANONICAL_RECEIPT = Receipt(
    client_address=CANONICAL_ADDRESS,
    node_address=(
        "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789"
    ),
    request_uuid="00000000-0000-0000-0000-000000000001",
    data_amount=1024,
    total_price=1000000000000000,
)
CANONICAL_SIGNATURE = (
    "0x15cbab3e32932fdfc01ebfb712b34ef1970f9b7b6e08318aea414ca1dbd4a2bf"
    "04d5812dda908013e42091ae473667dfbf6110432e1f4e3ee7b9543916c61dd41c"
)


def test_canonical_protocol_vector_recomputes_byte_for_byte():
    """§7 of v1.5-consumer-protocol.md — the join point with the JS SDK.

    Any drift in `eip712.py` would produce a different signature byte
    string. JS implementations MUST produce the same 65-byte hex blob; this
    test pins the Python side so we can detect a regression on a single PR.
    """
    sig = sign_receipt(CANONICAL_KEY, CANONICAL_RECEIPT, CANONICAL_DOMAIN)
    assert sig.lower() == CANONICAL_SIGNATURE.lower()


def test_canonical_protocol_vector_recovers_signer():
    recovered = recover_receipt_signer(
        CANONICAL_RECEIPT, CANONICAL_SIGNATURE, CANONICAL_DOMAIN,
    )
    assert recovered.lower() == CANONICAL_ADDRESS.lower()


def test_address_to_bytes32_pads_correctly():
    """Sanity check on the helper used to build node_address values."""
    addr = "0x9e46051b44b1639a8a9f8a53041c6f121c0fe789"
    padded = address_to_bytes32(addr)
    assert padded == (
        "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789"
    )
