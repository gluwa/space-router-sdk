"""Admin clients for the Space Router Coordination API.

Provides :class:`SpaceRouterAdmin` (sync) and :class:`AsyncSpaceRouterAdmin`
(async) for managing API keys.
"""

from __future__ import annotations

from typing import Any

import httpx

import warnings

from spacerouter.models import (
    ApiKey,
    ApiKeyInfo,
    BillingReissueResult,
    CheckoutSession,
    CreditLineStatus,
    Node,
    NodeStatus,
    RegisterChallenge,
    RegisterResult,
    TransferPage,
)

_DEFAULT_COORDINATION_URL = "https://coordination.spacerouter.org"


class SpaceRouterAdmin:
    """Synchronous admin client for the Coordination API.

    Example::

        with SpaceRouterAdmin() as admin:
            key = admin.create_api_key("my-agent")
            print(key.api_key)  # sr_live_...
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_COORDINATION_URL,
        *,
        timeout: float = 10.0,
        **httpx_kwargs: Any,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout, **httpx_kwargs
        )

    def create_api_key(self, name: str, *, rate_limit_rpm: int = 60) -> ApiKey:
        """Create a new API key.

        The raw key value is **only** available in the returned object.
        """
        response = self._client.post(
            "/api-keys",
            json={"name": name, "rate_limit_rpm": rate_limit_rpm},
        )
        response.raise_for_status()
        return ApiKey.model_validate(response.json())

    def list_api_keys(self) -> list[ApiKeyInfo]:
        """List all API keys (raw key values are never returned)."""
        response = self._client.get("/api-keys")
        response.raise_for_status()
        return [ApiKeyInfo.model_validate(item) for item in response.json()]

    def revoke_api_key(self, key_id: str) -> None:
        """Revoke an API key (soft-delete)."""
        response = self._client.delete(f"/api-keys/{key_id}")
        response.raise_for_status()

    # -- Node management -----------------------------------------------------

    def register_node(
        self,
        *,
        endpoint_url: str,
        identity_address: str | None = None,
        staking_address: str | None = None,
        collection_address: str | None = None,
        vouching_signature: str | None = None,
        vouching_timestamp: int | None = None,
        label: str | None = None,
        connectivity_type: str | None = None,
        wallet_address: str | None = None,
    ) -> Node:
        """Register a new proxy node.

        v0.2.0 accepts ``identity_address``, ``staking_address``,
        ``collection_address``, and a ``vouching_signature``.  The legacy
        ``wallet_address`` parameter is still accepted for backward
        compatibility.
        """
        if wallet_address is not None and identity_address is None:
            warnings.warn(
                "wallet_address is deprecated — use identity_address, "
                "staking_address, collection_address",
                DeprecationWarning,
                stacklevel=2,
            )
            identity_address = identity_address or wallet_address
            staking_address = staking_address or wallet_address
            collection_address = collection_address or wallet_address

        payload: dict[str, Any] = {
            "endpoint_url": endpoint_url,
            "identity_address": identity_address,
            "staking_address": staking_address,
            "collection_address": collection_address,
        }
        if vouching_signature is not None:
            payload["vouching_signature"] = vouching_signature
        if vouching_timestamp is not None:
            payload["vouching_timestamp"] = vouching_timestamp
        if label is not None:
            payload["label"] = label
        if connectivity_type is not None:
            payload["connectivity_type"] = connectivity_type
        response = self._client.post("/nodes", json=payload)
        response.raise_for_status()
        return Node.model_validate(response.json())

    def register_node_with_identity(
        self,
        *,
        private_key: str,
        endpoint_url: str,
        staking_address: str,
        collection_address: str | None = None,
        label: str | None = None,
        connectivity_type: str | None = None,
    ) -> Node:
        """Register a node using an identity key.

        Derives the identity address and creates the vouching signature
        automatically.  If ``collection_address`` is *None*, defaults to
        the identity address.
        """
        from spacerouter.identity import create_vouching_signature, get_address

        identity_addr = get_address(private_key)
        coll_addr = collection_address or identity_addr
        sig, ts = create_vouching_signature(private_key, staking_address, coll_addr)
        return self.register_node(
            endpoint_url=endpoint_url,
            identity_address=identity_addr,
            staking_address=staking_address,
            collection_address=coll_addr,
            vouching_signature=sig,
            vouching_timestamp=ts,
            label=label,
            connectivity_type=connectivity_type,
        )

    def list_nodes(self) -> list[Node]:
        """List all registered nodes."""
        response = self._client.get("/nodes")
        response.raise_for_status()
        return [Node.model_validate(item) for item in response.json()]

    def update_node_status(
        self, node_id: str, *, status: NodeStatus, private_key: str,
    ) -> None:
        """Update a node's operational status (offline or draining only). Requires identity key."""
        from spacerouter.identity import get_address, sign_request

        addr = get_address(private_key)
        sig, ts = sign_request(private_key, "update_status", node_id)
        response = self._client.patch(
            f"/nodes/{node_id}/status",
            json={"status": status, "identity_address": addr, "wallet_address": addr, "signature": sig, "timestamp": ts},
        )
        response.raise_for_status()

    def request_probe(self, node_id: str, *, private_key: str) -> None:
        """Request a health probe for an offline node. Requires identity key."""
        from spacerouter.identity import get_address, sign_request

        addr = get_address(private_key)
        sig, ts = sign_request(private_key, "request_probe", node_id)
        response = self._client.post(
            f"/nodes/{node_id}/request-probe",
            json={"identity_address": addr, "wallet_address": addr, "signature": sig, "timestamp": ts},
        )
        response.raise_for_status()

    def delete_node(self, node_id: str, *, private_key: str) -> None:
        """Delete a registered node. Requires identity key."""
        from spacerouter.identity import get_address, sign_request

        addr = get_address(private_key)
        sig, ts = sign_request(private_key, "delete_node", node_id)
        response = self._client.request(
            "DELETE", f"/nodes/{node_id}",
            json={"identity_address": addr, "wallet_address": addr, "signature": sig, "timestamp": ts},
        )
        response.raise_for_status()

    # -- Staking registration ------------------------------------------------

    def get_register_challenge(self, address: str) -> RegisterChallenge:
        """Request a signing challenge for Creditcoin staking registration."""
        response = self._client.post(
            "/nodes/register/challenge", json={"address": address}
        )
        response.raise_for_status()
        return RegisterChallenge.model_validate(response.json())

    def verify_and_register(
        self,
        *,
        address: str,
        endpoint_url: str,
        signed_nonce: str,
        label: str | None = None,
    ) -> RegisterResult:
        """Verify a signed nonce and register the node via staking."""
        payload: dict[str, Any] = {
            "address": address,
            "endpoint_url": endpoint_url,
            "signed_nonce": signed_nonce,
        }
        if label is not None:
            payload["label"] = label
        response = self._client.post("/nodes/register/verify", json=payload)
        response.raise_for_status()
        return RegisterResult.model_validate(response.json())

    # -- Billing -------------------------------------------------------------

    def create_checkout(self, email: str) -> CheckoutSession:
        """Create a Stripe checkout session."""
        response = self._client.post("/billing/checkout", json={"email": email})
        response.raise_for_status()
        return CheckoutSession.model_validate(response.json())

    def verify_email(self, token: str) -> None:
        """Verify an email address with a token."""
        response = self._client.get("/billing/verify", params={"token": token})
        response.raise_for_status()

    def reissue_api_key(self, *, email: str, token: str) -> BillingReissueResult:
        """Reissue an API key using email verification."""
        response = self._client.post(
            "/billing/reissue", json={"email": email, "token": token}
        )
        response.raise_for_status()
        return BillingReissueResult.model_validate(response.json())

    # -- Credit lines (v0.2.0) -----------------------------------------------

    def get_credit_line(self, address: str) -> CreditLineStatus:
        """Query credit line status for an address."""
        response = self._client.get(f"/credit-lines/{address}")
        response.raise_for_status()
        return CreditLineStatus.model_validate(response.json())

    # -- Dashboard -----------------------------------------------------------

    def get_transfers(
        self,
        *,
        identity_address: str | None = None,
        wallet_address: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> TransferPage:
        """Get paginated data transfer history.

        Accepts ``identity_address`` (v0.2.0) or the deprecated
        ``wallet_address`` alias.
        """
        addr = identity_address or wallet_address
        if addr is None:
            raise ValueError("identity_address (or wallet_address) is required")
        if wallet_address is not None and identity_address is None:
            warnings.warn(
                "wallet_address is deprecated — use identity_address",
                DeprecationWarning,
                stacklevel=2,
            )
        params: dict[str, Any] = {"wallet_address": addr}
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["page_size"] = page_size
        response = self._client.get("/dashboard/transfers", params=params)
        response.raise_for_status()
        return TransferPage.model_validate(response.json())

    # -- Lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SpaceRouterAdmin:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class AsyncSpaceRouterAdmin:
    """Asynchronous admin client for the Coordination API.

    Example::

        async with AsyncSpaceRouterAdmin() as admin:
            key = await admin.create_api_key("my-agent")
            print(key.api_key)
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_COORDINATION_URL,
        *,
        timeout: float = 10.0,
        **httpx_kwargs: Any,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, **httpx_kwargs
        )

    async def create_api_key(self, name: str, *, rate_limit_rpm: int = 60) -> ApiKey:
        """Create a new API key."""
        response = await self._client.post(
            "/api-keys",
            json={"name": name, "rate_limit_rpm": rate_limit_rpm},
        )
        response.raise_for_status()
        return ApiKey.model_validate(response.json())

    async def list_api_keys(self) -> list[ApiKeyInfo]:
        """List all API keys."""
        response = await self._client.get("/api-keys")
        response.raise_for_status()
        return [ApiKeyInfo.model_validate(item) for item in response.json()]

    async def revoke_api_key(self, key_id: str) -> None:
        """Revoke an API key (soft-delete)."""
        response = await self._client.delete(f"/api-keys/{key_id}")
        response.raise_for_status()

    # -- Node management -----------------------------------------------------

    async def register_node(
        self,
        *,
        endpoint_url: str,
        identity_address: str | None = None,
        staking_address: str | None = None,
        collection_address: str | None = None,
        vouching_signature: str | None = None,
        vouching_timestamp: int | None = None,
        label: str | None = None,
        connectivity_type: str | None = None,
        wallet_address: str | None = None,
    ) -> Node:
        """Register a new proxy node (see sync variant for details)."""
        if wallet_address is not None and identity_address is None:
            warnings.warn(
                "wallet_address is deprecated — use identity_address, "
                "staking_address, collection_address",
                DeprecationWarning,
                stacklevel=2,
            )
            identity_address = identity_address or wallet_address
            staking_address = staking_address or wallet_address
            collection_address = collection_address or wallet_address

        payload: dict[str, Any] = {
            "endpoint_url": endpoint_url,
            "identity_address": identity_address,
            "staking_address": staking_address,
            "collection_address": collection_address,
        }
        if vouching_signature is not None:
            payload["vouching_signature"] = vouching_signature
        if vouching_timestamp is not None:
            payload["vouching_timestamp"] = vouching_timestamp
        if label is not None:
            payload["label"] = label
        if connectivity_type is not None:
            payload["connectivity_type"] = connectivity_type
        response = await self._client.post("/nodes", json=payload)
        response.raise_for_status()
        return Node.model_validate(response.json())

    async def register_node_with_identity(
        self,
        *,
        private_key: str,
        endpoint_url: str,
        staking_address: str,
        collection_address: str | None = None,
        label: str | None = None,
        connectivity_type: str | None = None,
    ) -> Node:
        """Register a node using an identity key (see sync variant for details)."""
        from spacerouter.identity import create_vouching_signature, get_address

        identity_addr = get_address(private_key)
        coll_addr = collection_address or identity_addr
        sig, ts = create_vouching_signature(private_key, staking_address, coll_addr)
        return await self.register_node(
            endpoint_url=endpoint_url,
            identity_address=identity_addr,
            staking_address=staking_address,
            collection_address=coll_addr,
            vouching_signature=sig,
            vouching_timestamp=ts,
            label=label,
            connectivity_type=connectivity_type,
        )

    async def list_nodes(self) -> list[Node]:
        """List all registered nodes."""
        response = await self._client.get("/nodes")
        response.raise_for_status()
        return [Node.model_validate(item) for item in response.json()]

    async def update_node_status(
        self, node_id: str, *, status: NodeStatus, private_key: str,
    ) -> None:
        """Update a node's operational status (offline or draining only). Requires identity key."""
        from spacerouter.identity import get_address, sign_request

        addr = get_address(private_key)
        sig, ts = sign_request(private_key, "update_status", node_id)
        response = await self._client.patch(
            f"/nodes/{node_id}/status",
            json={"status": status, "identity_address": addr, "wallet_address": addr, "signature": sig, "timestamp": ts},
        )
        response.raise_for_status()

    async def request_probe(self, node_id: str, *, private_key: str) -> None:
        """Request a health probe for an offline node. Requires identity key."""
        from spacerouter.identity import get_address, sign_request

        addr = get_address(private_key)
        sig, ts = sign_request(private_key, "request_probe", node_id)
        response = await self._client.post(
            f"/nodes/{node_id}/request-probe",
            json={"identity_address": addr, "wallet_address": addr, "signature": sig, "timestamp": ts},
        )
        response.raise_for_status()

    async def delete_node(self, node_id: str, *, private_key: str) -> None:
        """Delete a registered node. Requires identity key."""
        from spacerouter.identity import get_address, sign_request

        addr = get_address(private_key)
        sig, ts = sign_request(private_key, "delete_node", node_id)
        response = await self._client.request(
            "DELETE", f"/nodes/{node_id}",
            json={"identity_address": addr, "wallet_address": addr, "signature": sig, "timestamp": ts},
        )
        response.raise_for_status()

    # -- Staking registration ------------------------------------------------

    async def get_register_challenge(self, address: str) -> RegisterChallenge:
        """Request a signing challenge for Creditcoin staking registration."""
        response = await self._client.post(
            "/nodes/register/challenge", json={"address": address}
        )
        response.raise_for_status()
        return RegisterChallenge.model_validate(response.json())

    async def verify_and_register(
        self,
        *,
        address: str,
        endpoint_url: str,
        signed_nonce: str,
        label: str | None = None,
    ) -> RegisterResult:
        """Verify a signed nonce and register the node via staking."""
        payload: dict[str, Any] = {
            "address": address,
            "endpoint_url": endpoint_url,
            "signed_nonce": signed_nonce,
        }
        if label is not None:
            payload["label"] = label
        response = await self._client.post("/nodes/register/verify", json=payload)
        response.raise_for_status()
        return RegisterResult.model_validate(response.json())

    # -- Billing -------------------------------------------------------------

    async def create_checkout(self, email: str) -> CheckoutSession:
        """Create a Stripe checkout session."""
        response = await self._client.post(
            "/billing/checkout", json={"email": email}
        )
        response.raise_for_status()
        return CheckoutSession.model_validate(response.json())

    async def verify_email(self, token: str) -> None:
        """Verify an email address with a token."""
        response = await self._client.get(
            "/billing/verify", params={"token": token}
        )
        response.raise_for_status()

    async def reissue_api_key(
        self, *, email: str, token: str
    ) -> BillingReissueResult:
        """Reissue an API key using email verification."""
        response = await self._client.post(
            "/billing/reissue", json={"email": email, "token": token}
        )
        response.raise_for_status()
        return BillingReissueResult.model_validate(response.json())

    # -- Credit lines (v0.2.0) -----------------------------------------------

    async def get_credit_line(self, address: str) -> CreditLineStatus:
        """Query credit line status for an address."""
        response = await self._client.get(f"/credit-lines/{address}")
        response.raise_for_status()
        return CreditLineStatus.model_validate(response.json())

    # -- Dashboard -----------------------------------------------------------

    async def get_transfers(
        self,
        *,
        identity_address: str | None = None,
        wallet_address: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> TransferPage:
        """Get paginated data transfer history (see sync variant for details)."""
        addr = identity_address or wallet_address
        if addr is None:
            raise ValueError("identity_address (or wallet_address) is required")
        if wallet_address is not None and identity_address is None:
            warnings.warn(
                "wallet_address is deprecated — use identity_address",
                DeprecationWarning,
                stacklevel=2,
            )
        params: dict[str, Any] = {"wallet_address": addr}
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["page_size"] = page_size
        response = await self._client.get("/dashboard/transfers", params=params)
        response.raise_for_status()
        return TransferPage.model_validate(response.json())

    # -- Lifecycle -----------------------------------------------------------

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncSpaceRouterAdmin:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
