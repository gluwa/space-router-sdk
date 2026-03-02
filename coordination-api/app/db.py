import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Thin wrapper around Supabase PostgREST API."""

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._base_url = f"{settings.SUPABASE_URL}/rest/v1"
        self._headers = {
            "apikey": settings.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        }

    async def select(
        self,
        table: str,
        *,
        params: dict[str, str] | None = None,
        single: bool = False,
    ) -> list[dict] | dict | None:
        headers = {**self._headers}
        if single:
            headers["Accept"] = "application/vnd.pgrst.object+json"
        resp = await self._client.get(
            f"{self._base_url}/{table}",
            params=params or {},
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code == 406 and single:
            return None
        resp.raise_for_status()
        return resp.json()

    async def insert(self, table: str, data: dict | list[dict], *, return_rows: bool = True) -> list[dict] | None:
        headers = {**self._headers}
        if return_rows:
            headers["Prefer"] = "return=representation"
        else:
            headers["Prefer"] = "return=minimal"
        resp = await self._client.post(
            f"{self._base_url}/{table}",
            json=data,
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        if return_rows:
            return resp.json()
        return None

    async def update(
        self,
        table: str,
        data: dict,
        *,
        params: dict[str, str],
        return_rows: bool = False,
    ) -> list[dict] | None:
        headers = {**self._headers}
        if return_rows:
            headers["Prefer"] = "return=representation"
        else:
            headers["Prefer"] = "return=minimal"
        resp = await self._client.patch(
            f"{self._base_url}/{table}",
            json=data,
            params=params,
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        if return_rows:
            return resp.json()
        return None

    async def delete(self, table: str, *, params: dict[str, str]) -> None:
        resp = await self._client.delete(
            f"{self._base_url}/{table}",
            params=params,
            headers=self._headers,
            timeout=10.0,
        )
        resp.raise_for_status()

    async def rpc(self, function_name: str, params: dict | None = None) -> dict | list:
        resp = await self._client.post(
            f"{self._base_url}/rpc/{function_name}",
            json=params or {},
            headers=self._headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()
