"""Admin clients for the Space Router Coordination API.

Provides :class:`SpaceRouterAdmin` (sync) and :class:`AsyncSpaceRouterAdmin`
(async) for managing API keys.
"""

from __future__ import annotations

from typing import Any

import httpx

from spacerouter.models import (
    ApiKey,
    ApiKeyInfo,
    BillingReissueResult,
    CheckoutSession,
    Node,
    RegisterChallenge,
    RegisterResult,
    TransferPage,
)
from spacerouter.models import NodeStatus

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
        wallet_address: str,
        label: str | None = None,
        connectivity_type: str | None = None,
    ) -> Node:
        """Register a new proxy node."""
        payload: dict[str, Any] = {
            "endpoint_url": endpoint_url,
            "wallet_address": wallet_address,
        }
        if label is not None:
            payload["label"] = label
        if connectivity_type is not None:
            payload["connectivity_type"] = connectivity_type
        response = self._client.post("/nodes", json=payload)
        response.raise_for_status()
        return Node.model_validate(response.json())

    def list_nodes(self) -> list[Node]:
        """List all registered nodes."""
        response = self._client.get("/nodes")
        response.raise_for_status()
        return [Node.model_validate(item) for item in response.json()]

    def update_node_status(self, node_id: str, *, status: NodeStatus) -> None:
        """Update a node's operational status."""
        response = self._client.patch(
            f"/nodes/{node_id}/status", json={"status": status}
        )
        response.raise_for_status()

    def delete_node(self, node_id: str) -> None:
        """Delete a registered node."""
        response = self._client.delete(f"/nodes/{node_id}")
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

    # -- Dashboard -----------------------------------------------------------

    def get_transfers(
        self,
        *,
        wallet_address: str,
        page: int | None = None,
        page_size: int | None = None,
    ) -> TransferPage:
        """Get paginated data transfer history."""
        params: dict[str, Any] = {"wallet_address": wallet_address}
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
        wallet_address: str,
        label: str | None = None,
        connectivity_type: str | None = None,
    ) -> Node:
        """Register a new proxy node."""
        payload: dict[str, Any] = {
            "endpoint_url": endpoint_url,
            "wallet_address": wallet_address,
        }
        if label is not None:
            payload["label"] = label
        if connectivity_type is not None:
            payload["connectivity_type"] = connectivity_type
        response = await self._client.post("/nodes", json=payload)
        response.raise_for_status()
        return Node.model_validate(response.json())

    async def list_nodes(self) -> list[Node]:
        """List all registered nodes."""
        response = await self._client.get("/nodes")
        response.raise_for_status()
        return [Node.model_validate(item) for item in response.json()]

    async def update_node_status(self, node_id: str, *, status: NodeStatus) -> None:
        """Update a node's operational status."""
        response = await self._client.patch(
            f"/nodes/{node_id}/status", json={"status": status}
        )
        response.raise_for_status()

    async def delete_node(self, node_id: str) -> None:
        """Delete a registered node."""
        response = await self._client.delete(f"/nodes/{node_id}")
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

    # -- Dashboard -----------------------------------------------------------

    async def get_transfers(
        self,
        *,
        wallet_address: str,
        page: int | None = None,
        page_size: int | None = None,
    ) -> TransferPage:
        """Get paginated data transfer history."""
        params: dict[str, Any] = {"wallet_address": wallet_address}
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
