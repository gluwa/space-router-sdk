"""Tests for SpaceRouter Python SDK payment modules (Phase 5).

Covers:
- ClientPaymentWallet (challenge signing, receipt signing, auth headers)
- EIP-712 Receipt types (signing, recovery, serialization)
- SpaceRouterSPACE client (receipt validation, header building)
- EscrowClient (balance queries, deposit validation)
"""

import uuid

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from spacerouter.payment.eip712 import (
    EIP712Domain,
    Receipt,
    address_to_bytes32,
    recover_receipt_signer,
    sign_receipt,
)
from spacerouter.payment.client_wallet import ClientPaymentWallet
from spacerouter.payment.spacecoin_client import SpaceRouterSPACE
from spacerouter.escrow import EscrowClient

# ── Constants ─────────────────────────────────────────────────────────

CLIENT_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
CLIENT_ADDRESS = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
GATEWAY_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
GATEWAY_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

TEST_DOMAIN = EIP712Domain(
    name="TokenPaymentEscrow",
    version="1",
    chain_id=102031,
    verifying_contract="0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
)


# ── ClientPaymentWallet ───────────────────────────────────────────────


class TestClientPaymentWallet:
    def test_creates_with_address(self):
        w = ClientPaymentWallet(CLIENT_KEY)
        assert w.address.lower() == CLIENT_ADDRESS.lower()

    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="required"):
            ClientPaymentWallet("")

    def test_sign_challenge(self):
        w = ClientPaymentWallet(CLIENT_KEY)
        challenge = "a" * 64
        sig = w.sign_challenge(challenge)
        assert sig.startswith("0x")

        # Verify with EIP-191 recovery
        message = f"space-router:challenge:{challenge}"
        signable = encode_defunct(text=message)
        recovered = Account.recover_message(
            signable, signature=bytes.fromhex(sig[2:])
        )
        assert recovered.lower() == CLIENT_ADDRESS.lower()

    def test_sign_receipt(self):
        w = ClientPaymentWallet(CLIENT_KEY)
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1000,
            total_price=50,
        )
        sig = w.sign_receipt(receipt, TEST_DOMAIN)
        assert sig.startswith("0x")

        recovered = recover_receipt_signer(receipt, sig, TEST_DOMAIN)
        assert recovered.lower() == CLIENT_ADDRESS.lower()

    def test_build_auth_headers(self):
        w = ClientPaymentWallet(CLIENT_KEY)
        headers = w.build_auth_headers("abc123")
        assert headers["X-SpaceRouter-Payment-Address"] == w.address
        assert headers["X-SpaceRouter-Identity-Address"] == w.address
        assert headers["X-SpaceRouter-Challenge"] == "abc123"
        assert headers["X-SpaceRouter-Challenge-Signature"].startswith("0x")

    def test_verify_receipt_signature_valid(self):
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid="test-uuid",
            data_amount=100,
            total_price=10,
        )
        sig = sign_receipt(CLIENT_KEY, receipt, TEST_DOMAIN)
        assert ClientPaymentWallet.verify_receipt_signature(
            receipt, sig, TEST_DOMAIN, CLIENT_ADDRESS,
        ) is True

    def test_verify_receipt_signature_wrong_signer(self):
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid="test-uuid",
            data_amount=100,
            total_price=10,
        )
        sig = sign_receipt(GATEWAY_KEY, receipt, TEST_DOMAIN)  # Wrong key
        assert ClientPaymentWallet.verify_receipt_signature(
            receipt, sig, TEST_DOMAIN, CLIENT_ADDRESS,
        ) is False


# ── SpaceRouterSPACE ──────────────────────────────────────────────────


class TestSpaceRouterSPACE:
    def _make_client(self, **overrides) -> SpaceRouterSPACE:
        defaults = {
            "gateway_url": "http://localhost:8081",
            "proxy_url": "http://localhost:8080",
            "private_key": CLIENT_KEY,
            "chain_id": 102031,
            "escrow_contract": "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
        }
        defaults.update(overrides)
        return SpaceRouterSPACE(**defaults)

    def test_creates_with_address(self):
        c = self._make_client()
        assert c.address.lower() == CLIENT_ADDRESS.lower()

    def test_build_auth_headers(self):
        c = self._make_client()
        headers = c.build_auth_headers("challenge123")
        assert "X-SpaceRouter-Payment-Address" in headers
        assert "X-SpaceRouter-Challenge-Signature" in headers

    def test_sign_receipt(self):
        c = self._make_client()
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=5000,
            total_price=100,
        )
        sig = c.sign_receipt(receipt)
        assert sig.startswith("0x")

        recovered = recover_receipt_signer(receipt, sig, c.domain)
        assert recovered.lower() == CLIENT_ADDRESS.lower()

    def test_validate_receipt_valid(self):
        c = self._make_client()
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1024 ** 3,
            total_price=10 ** 18,
        )
        valid, errors = c.validate_receipt(receipt)
        assert valid is True
        assert errors == []

    def test_validate_receipt_wrong_address(self):
        c = self._make_client()
        receipt = Receipt(
            client_address=GATEWAY_ADDRESS,  # Wrong
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1000,
            total_price=10,
        )
        valid, errors = c.validate_receipt(receipt)
        assert valid is False
        assert any("mismatch" in e for e in errors)

    def test_validate_receipt_excessive_rate(self):
        c = self._make_client(max_rate_per_gb=10 ** 18)  # 1 SPACE/GB max
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1024,  # 1 KB
            total_price=10 ** 18,  # 1 SPACE for 1 KB = way too expensive
        )
        valid, errors = c.validate_receipt(receipt)
        assert valid is False
        assert any("rate" in e.lower() for e in errors)

    def test_validate_receipt_no_rate_limit(self):
        c = self._make_client(max_rate_per_gb=None)
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1024,
            total_price=10 ** 18,  # Expensive but no limit set
        )
        valid, errors = c.validate_receipt(receipt)
        assert valid is True


# ── EscrowClient ──────────────────────────────────────────────────────


class TestEscrowClientSDK:
    def test_escrow_client_instantiation(self):
        """EscrowClient can be instantiated (lazy RPC connect)."""
        client = EscrowClient(
            "http://fake:8545",
            "0x0000000000000000000000000000000000000001",
        )
        assert client.address == ""  # No private key

    def test_deposit_requires_positive(self):
        """EscrowClient.deposit should reject zero/negative amounts."""
        client = EscrowClient(
            "http://fake:8545",
            "0x0000000000000000000000000000000000000001",
            private_key=CLIENT_KEY,
        )
        with pytest.raises(ValueError, match="positive"):
            client.deposit(0)

    def test_address_to_bytes32(self):
        b32 = address_to_bytes32(CLIENT_ADDRESS)
        assert len(b32) == 66
        assert b32.startswith("0x")

    def test_receipt_json_roundtrip(self):
        r = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid="test-uuid-sdk",
            data_amount=9999,
            total_price=42,
        )
        d = r.to_json_dict()
        restored = Receipt.from_json_dict(d)
        assert restored.client_address == r.client_address
        assert restored.request_uuid == r.request_uuid
        assert restored.data_amount == r.data_amount
        assert restored.total_price == r.total_price


# ── Byte count validation (new in feat/sdk-byte-validation) ───────────

class TestByteCountValidation:
    """SpaceRouterSPACE.validate_receipt rejects inflated dataAmount vs local count."""

    def _client(self, **kwargs):
        defaults = dict(
            gateway_url="http://gw:8081",
            proxy_url="http://gw:8080",
            private_key=CLIENT_KEY,
            chain_id=TEST_DOMAIN.chain_id,
            escrow_contract=TEST_DOMAIN.verifying_contract,
        )
        defaults.update(kwargs)
        return SpaceRouterSPACE(**defaults)

    def _receipt(self, data_amount: int = 10_000, total_price: int = 0):
        return Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=data_amount,
            total_price=total_price,
        )

    def test_matching_bytes_pass(self):
        c = self._client()
        r = self._receipt(data_amount=10_000)
        ok, errors = c.validate_receipt(r, observed_bytes=10_000)
        assert ok, errors

    def test_within_tolerance_pass(self):
        """Gateway claims 5% more — default byte_tolerance is 5%."""
        c = self._client(byte_tolerance=0.05)
        r = self._receipt(data_amount=10_500)
        ok, _ = c.validate_receipt(r, observed_bytes=10_000)
        assert ok

    def test_over_tolerance_rejects(self):
        c = self._client(byte_tolerance=0.05)
        r = self._receipt(data_amount=50_000)  # 5x inflation
        ok, errors = c.validate_receipt(r, observed_bytes=10_000)
        assert not ok
        assert any("dataAmount" in e for e in errors)

    def test_absolute_floor_protects_small_requests(self):
        """Tiny observed byte count: absolute floor (1 KB default) must apply."""
        c = self._client(byte_tolerance=0.05, byte_tolerance_abs_min=1024)
        # observed=100, 5% = 5 bytes; floor says allow up to +1024 bytes slack
        r = self._receipt(data_amount=500)
        ok, _ = c.validate_receipt(r, observed_bytes=100)
        assert ok, "floor should tolerate overhead on tiny requests"

        # Over the floor → reject
        r2 = self._receipt(data_amount=2000)
        ok2, _ = c.validate_receipt(r2, observed_bytes=100)
        assert not ok2

    def test_no_observed_bytes_skips_check(self):
        """When caller doesn't supply observed_bytes, byte check is skipped."""
        c = self._client()
        r = self._receipt(data_amount=999_999_999)
        ok, _ = c.validate_receipt(r)  # no observed_bytes
        assert ok

    def test_sign_after_validation_raises_on_fraud(self):
        c = self._client(byte_tolerance=0.05)
        r = self._receipt(data_amount=50_000)
        with pytest.raises(ValueError, match="dataAmount"):
            c.sign_receipt_after_validation(r, observed_bytes=10_000)

    def test_sign_after_validation_signs_on_success(self):
        c = self._client()
        r = self._receipt(data_amount=10_000)
        sig = c.sign_receipt_after_validation(r, observed_bytes=10_000)
        assert sig.startswith("0x")
        assert len(sig) == 132  # 0x + 130 hex chars (65 bytes)


# ── HTTP-method guard (Fix 1) ─────────────────────────────────────────


class TestSpaceRouterSPACEHttpGuard:
    """``SpaceRouterSPACE`` is a wallet, not an HTTP client.

    Stale QA bundles still call ``consumer.get(url)``; we want a hint, not
    a cryptic AttributeError.
    """

    def _client(self) -> SpaceRouterSPACE:
        return SpaceRouterSPACE(
            gateway_url="http://localhost:8081",
            proxy_url="http://localhost:8080",
            private_key=CLIENT_KEY,
            chain_id=102031,
            escrow_contract="0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
        )

    @pytest.mark.parametrize(
        "verb",
        ["get", "post", "put", "patch", "delete", "head", "options", "request"],
    )
    def test_http_verb_access_raises_with_hint(self, verb):
        c = self._client()
        with pytest.raises(AttributeError) as exc_info:
            getattr(c, verb)
        msg = str(exc_info.value)
        # Must point the caller at the canonical wrap pattern.
        assert "payment=consumer" in msg
        assert "SpaceRouter" in msg
        assert f".{verb}()" in msg

    @pytest.mark.parametrize(
        "name",
        [
            "address", "wallet", "domain", "gateway_url", "proxy_url",
            "max_rate_per_gb", "byte_tolerance", "byte_tolerance_abs_min",
            "strict_settlement", "request_challenge", "build_auth_headers",
            "sign_receipt", "sync_receipts", "validate_receipt",
            "sign_receipt_after_validation",
        ],
    )
    def test_legitimate_attributes_resolve(self, name):
        c = self._client()
        # Just resolving (no AttributeError) is enough to prove __getattr__
        # doesn't shadow a real attribute / method. Some attributes (e.g.
        # max_rate_per_gb) default to None, which is fine.
        sentinel = object()
        assert getattr(c, name, sentinel) is not sentinel

    def test_truly_missing_attribute_still_raises(self):
        c = self._client()
        with pytest.raises(AttributeError):
            _ = c.no_such_attribute_xyz


# ── timeout / verify plumbing (Fix 2) ─────────────────────────────────


class TestSpaceRouterSPACEHttpKnobs:
    """``timeout`` and ``verify`` must reach ``httpx.AsyncClient``."""

    def _client(self, **overrides) -> SpaceRouterSPACE:
        defaults = {
            "gateway_url": "http://localhost:8081",
            "proxy_url": "http://localhost:8080",
            "private_key": CLIENT_KEY,
            "chain_id": 102031,
            "escrow_contract": "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
        }
        defaults.update(overrides)
        return SpaceRouterSPACE(**defaults)

    def test_default_timeout_and_verify(self):
        c = self._client()
        assert c._timeout == 30.0
        assert c._verify is True

    def test_custom_values_stored(self):
        c = self._client(timeout=60.0, verify=False)
        assert c._timeout == 60.0
        assert c._verify is False

    @pytest.mark.asyncio
    async def test_request_challenge_passes_verify_and_timeout(self, monkeypatch):
        """Verify ``httpx.AsyncClient(verify=...)`` and ``client.get(timeout=...)``
        both see the values configured on ``SpaceRouterSPACE``.
        """
        from spacerouter.payment import spacecoin_client as mod

        captured: dict = {"client_kwargs": None, "get_kwargs": None}

        class _StubResp:
            def raise_for_status(self): pass
            def json(self): return {"challenge": "abc"}

        class _StubClient:
            def __init__(self, *args, **kwargs):
                captured["client_kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, **kwargs):
                captured["get_kwargs"] = kwargs
                return _StubResp()

        monkeypatch.setattr(mod.httpx, "AsyncClient", _StubClient)

        c = self._client(timeout=60.0, verify=False)
        challenge = await c.request_challenge()
        assert challenge == "abc"
        assert captured["client_kwargs"] == {"verify": False}
        assert captured["get_kwargs"] == {"timeout": 60.0}

    @pytest.mark.asyncio
    async def test_request_challenge_default_kwargs(self, monkeypatch):
        from spacerouter.payment import spacecoin_client as mod

        captured: dict = {}

        class _StubResp:
            def raise_for_status(self): pass
            def json(self): return {"challenge": "ok"}

        class _StubClient:
            def __init__(self, *args, **kwargs):
                captured["client_kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, **kwargs):
                captured["get_kwargs"] = kwargs
                return _StubResp()

        monkeypatch.setattr(mod.httpx, "AsyncClient", _StubClient)

        c = self._client()
        await c.request_challenge()
        assert captured["client_kwargs"] == {"verify": True}
        assert captured["get_kwargs"] == {"timeout": 30.0}

    @pytest.mark.asyncio
    async def test_sync_receipts_plumbs_timeout_verify(self, monkeypatch):
        """``sync_receipts`` instantiates ``ConsumerSettlementClient`` with
        the same ``timeout`` and ``verify`` configured on the wallet.
        """
        from spacerouter.payment import spacecoin_client as mod

        captured: dict = {}

        class _StubSettler:
            def __init__(self, **kwargs):
                captured["init_kwargs"] = kwargs

            async def sync_receipts(self, *, limit, strict):
                captured["sync_kwargs"] = {"limit": limit, "strict": strict}
                return {"accepted": [], "rejected": [], "pending_count": 0}

        # Patch the lazily-imported symbol at its source module so
        # SpaceRouterSPACE.sync_receipts picks up the stub.
        from spacerouter.payment import consumer_settlement
        monkeypatch.setattr(
            consumer_settlement, "ConsumerSettlementClient", _StubSettler,
        )

        c = self._client(timeout=45.0, verify="/etc/ssl/cert.pem")
        result = await c.sync_receipts(limit=5)
        assert result["pending_count"] == 0
        assert captured["init_kwargs"]["timeout"] == 45.0
        assert captured["init_kwargs"]["verify"] == "/etc/ssl/cert.pem"
        assert captured["init_kwargs"]["gateway_url"] == "http://localhost:8081"
        assert captured["sync_kwargs"] == {"limit": 5, "strict": False}


# ── management_url plumbing (Fix: MAJ-1) ──────────────────────────────


class TestSpaceRouterSPACEManagementURL:
    """``management_url`` decouples the management API from the proxy URL.

    Previously ``gateway_url`` did double duty: callers who passed the
    proxy listener URL there ate ``HTTP 407`` from
    ``GET /auth/challenge`` because the proxy port only speaks CONNECT.
    """

    def _client(self, **overrides) -> SpaceRouterSPACE:
        defaults = {
            "gateway_url": "http://localhost:8080",  # proxy URL
            "proxy_url": "http://localhost:8080",
            "private_key": CLIENT_KEY,
            "chain_id": 102031,
            "escrow_contract": "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
        }
        defaults.update(overrides)
        return SpaceRouterSPACE(**defaults)

    def test_management_url_defaults_to_gateway_url(self):
        """Backward compat: omit ``management_url`` → fall back to gateway."""
        c = self._client()
        assert c.management_url == "http://localhost:8080"

    def test_management_url_overrides_gateway_url(self):
        c = self._client(management_url="http://localhost:8081")
        assert c.management_url == "http://localhost:8081"
        # gateway_url left untouched.
        assert c.gateway_url == "http://localhost:8080"

    def test_management_url_strips_trailing_slash(self):
        c = self._client(management_url="http://localhost:8081/")
        assert c.management_url == "http://localhost:8081"

    @pytest.mark.asyncio
    async def test_request_challenge_hits_management_url(self, monkeypatch):
        from spacerouter.payment import spacecoin_client as mod

        captured: dict = {}

        class _StubResp:
            def raise_for_status(self): pass
            def json(self): return {"challenge": "ok"}

        class _StubClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False
            async def get(self, url, **kwargs):
                captured["url"] = url
                return _StubResp()

        monkeypatch.setattr(mod.httpx, "AsyncClient", _StubClient)

        c = self._client(management_url="http://localhost:8081")
        await c.request_challenge()
        # MUST go to management URL, not the proxy gateway URL.
        assert captured["url"] == "http://localhost:8081/auth/challenge"

    @pytest.mark.asyncio
    async def test_request_challenge_falls_back_to_gateway_url(self, monkeypatch):
        """When ``management_url`` omitted, behaviour matches rc.5."""
        from spacerouter.payment import spacecoin_client as mod

        captured: dict = {}

        class _StubResp:
            def raise_for_status(self): pass
            def json(self): return {"challenge": "ok"}

        class _StubClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False
            async def get(self, url, **kwargs):
                captured["url"] = url
                return _StubResp()

        monkeypatch.setattr(mod.httpx, "AsyncClient", _StubClient)

        c = self._client(gateway_url="http://localhost:9999")
        await c.request_challenge()
        assert captured["url"] == "http://localhost:9999/auth/challenge"

    @pytest.mark.asyncio
    async def test_sync_receipts_uses_management_url(self, monkeypatch):
        """ConsumerSettlementClient must be built with the management URL."""
        captured: dict = {}

        class _StubSettler:
            def __init__(self, **kwargs):
                captured["init_kwargs"] = kwargs
            async def sync_receipts(self, *, limit, strict):
                return {"accepted": [], "rejected": [], "pending_count": 0}

        from spacerouter.payment import consumer_settlement
        monkeypatch.setattr(
            consumer_settlement, "ConsumerSettlementClient", _StubSettler,
        )

        c = self._client(
            gateway_url="http://localhost:8080",
            management_url="http://localhost:8081",
        )
        await c.sync_receipts()
        assert captured["init_kwargs"]["gateway_url"] == "http://localhost:8081"

