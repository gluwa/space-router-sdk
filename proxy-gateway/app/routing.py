import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class NodeSelection:
    node_id: str
    endpoint_url: str


class NodeRouter:
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings

    async def select_node(self) -> NodeSelection | None:
        try:
            resp = await self._client.get(
                f"{self._settings.COORDINATION_API_URL}/internal/route/select",
                headers={"Authorization": f"Bearer {self._settings.COORDINATION_API_SECRET}"},
                timeout=5.0,
            )
        except httpx.HTTPError as e:
            logger.error("Failed to select node: %s", e)
            return None

        if resp.status_code == 200:
            data = resp.json()
            return NodeSelection(
                node_id=data["node_id"],
                endpoint_url=data["endpoint_url"],
            )

        if resp.status_code == 503:
            logger.warning("No nodes available")
        else:
            logger.error("Unexpected response from route/select: %d", resp.status_code)
        return None

    def report_outcome(
        self,
        node_id: str,
        success: bool,
        latency_ms: int,
        bytes_transferred: int,
    ) -> None:
        asyncio.create_task(self._do_report(node_id, success, latency_ms, bytes_transferred))

    async def _do_report(
        self,
        node_id: str,
        success: bool,
        latency_ms: int,
        bytes_transferred: int,
    ) -> None:
        try:
            await self._client.post(
                f"{self._settings.COORDINATION_API_URL}/internal/route/report",
                json={
                    "node_id": node_id,
                    "success": success,
                    "latency_ms": latency_ms,
                    "bytes": bytes_transferred,
                },
                headers={"Authorization": f"Bearer {self._settings.COORDINATION_API_SECRET}"},
                timeout=5.0,
            )
        except Exception as e:
            logger.warning("Failed to report route outcome: %s", e)
