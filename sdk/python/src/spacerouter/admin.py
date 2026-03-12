"""Admin clients for the Space Router Coordination API.

Provides :class:`SpaceRouterAdmin` (sync) and :class:`AsyncSpaceRouterAdmin`
(async) for managing API keys.
"""

from __future__ import annotations

from typing import Any

import httpx

from spacerouter.models import ApiKey, ApiKeyInfo

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

    def fetch_ca_cert(self) -> str | None:
        """Fetch the proxy network CA certificate.

        Returns the PEM-encoded certificate, or ``None`` when the proxy
        network does not require a custom CA (HTTP 503).
        """
        response = self._client.get("/ca-cert")
        if response.status_code == 503:
            return None
        response.raise_for_status()
        return response.text

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

    async def fetch_ca_cert(self) -> str | None:
        """Fetch the proxy network CA certificate.

        Returns the PEM-encoded certificate, or ``None`` when the proxy
        network does not require a custom CA (HTTP 503).
        """
        response = await self._client.get("/ca-cert")
        if response.status_code == 503:
            return None
        response.raise_for_status()
        return response.text

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncSpaceRouterAdmin:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
