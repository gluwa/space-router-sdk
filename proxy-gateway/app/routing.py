"""Node routing components for selecting proxy nodes and tracking outcomes."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class NodeSelection:
    """Selected node for routing traffic."""

    node_id: str
    endpoint_url: str


class NodeRouter:
    """Routes HTTP/HTTPS requests to the best available node."""

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings

    async def select_node(
        self,
        region: str | None = None,
        node_type: str | None = None,
    ) -> Optional[NodeSelection]:
        """Select the best available node, forwarding routing hints to the
        coordination API so it can filter home nodes and fall back to Bright
        Data when no match is found.
        """
        params: dict[str, str] = {}
        if region:
            params["region"] = region
        if node_type:
            params["node_type"] = node_type

        try:
            response = await self._client.get(
                f"{self._settings.COORDINATION_API_URL}/internal/route/select",
                headers={"X-Internal-API-Key": self._settings.COORDINATION_API_SECRET},
                params=params,
                timeout=5.0,
            )
            if response.status_code == 503:
                return None
            if response.status_code != 200:
                logger.error(
                    "Unexpected status from route/select: %d", response.status_code
                )
                return None

            data = response.json()
            return NodeSelection(
                node_id=data["node_id"],
                endpoint_url=data["endpoint_url"],
            )
        except httpx.RequestError:
            logger.exception("Failed to reach coordination API for node selection")
            return None

    def report_outcome(
        self,
        node_id: str,
        success: bool,
        latency_ms: int,
        bytes_transferred: int,
    ) -> None:
        """Fire-and-forget outcome report to update node health scores."""

        async def _do_report() -> None:
            try:
                await self._client.post(
                    f"{self._settings.COORDINATION_API_URL}/internal/route/report",
                    headers={"X-Internal-API-Key": self._settings.COORDINATION_API_SECRET},
                    json={
                        "node_id": node_id,
                        "success": success,
                        "latency_ms": latency_ms,
                        "bytes": bytes_transferred,
                    },
                    timeout=5.0,
                )
            except Exception:
                logger.exception("Failed to report outcome for node %s", node_id)

        try:
            asyncio.get_event_loop().create_task(_do_report())
        except RuntimeError:
            logger.warning("No event loop to schedule report for node %s", node_id)
