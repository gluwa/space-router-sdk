"""Routing service for selecting nodes and tracking outcomes."""

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ProxyNode:
    """Data class for a proxy node."""

    node_id: str
    endpoint_url: str
    health_score: float
    ip_type: str = ""
    ip_region: str = ""


class RoutingService:
    """Selects optimal nodes for routing traffic."""

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings

        # Local cache of nodes for SQLite implementation
        self._nodes_cache: Dict[str, ProxyNode] = {}
        self._node_health: Dict[str, float] = {}

    async def select_node(
        self,
        *,
        ip_type: Optional[str] = None,
        ip_region: Optional[str] = None,
    ) -> Optional[ProxyNode]:
        """Select the best available node for routing traffic.

        If *ip_type* or *ip_region* are provided, only nodes matching those
        filters are considered.  Falls back to any available node if no
        matches are found.
        """
        # SQLite implementation for local testing
        if hasattr(self._settings, "USE_SQLITE") and self._settings.USE_SQLITE:
            return await self._select_node_sqlite(ip_type=ip_type, ip_region=ip_region)

        # This would handle the Supabase implementation
        return self._get_fallback_node()

    async def _select_node_sqlite(
        self,
        *,
        ip_type: Optional[str] = None,
        ip_region: Optional[str] = None,
    ) -> Optional[ProxyNode]:
        """Select a node using SQLite data with optional ip_type/ip_region filtering."""
        if not self._nodes_cache:
            # For testing, create a mock local node
            node = ProxyNode(
                node_id="local-test-node-id",
                endpoint_url="http://127.0.0.1:9090",
                health_score=1.0,
            )
            self._nodes_cache[node.node_id] = node
            return node

        candidates = list(self._nodes_cache.values())

        # Apply filters if specified
        if ip_type or ip_region:
            filtered = candidates
            if ip_type:
                filtered = [n for n in filtered if n.ip_type == ip_type]
            if ip_region:
                # Case-insensitive substring match for region
                region_lower = ip_region.lower()
                filtered = [n for n in filtered if region_lower in (n.ip_region or "").lower()]

            if filtered:
                candidates = filtered
            else:
                logger.warning(
                    "No nodes match ip_type=%s ip_region=%s — falling back to all nodes",
                    ip_type, ip_region,
                )

        selected = random.choice(candidates)
        return selected

    def _get_fallback_node(self) -> Optional[ProxyNode]:
        """Get a fallback proxy provider when no residential nodes are available."""
        # Check if Proxyjet is configured
        if not self._settings.PROXYJET_HOST:
            return None

        auth = None
        if self._settings.PROXYJET_USERNAME and self._settings.PROXYJET_PASSWORD:
            auth = f"{self._settings.PROXYJET_USERNAME}:{self._settings.PROXYJET_PASSWORD}"

        endpoint_url = self._proxyjet_endpoint_url(auth)
        return ProxyNode(
            node_id="proxyjet-fallback",
            endpoint_url=endpoint_url,
            health_score=1.0,
        )

    def _proxyjet_endpoint_url(self, auth: Optional[str]) -> str:
        """Build the Proxyjet endpoint URL with auth if provided."""
        if auth:
            return f"http://{auth}@{self._settings.PROXYJET_HOST}:{self._settings.PROXYJET_PORT}"
        return f"http://{self._settings.PROXYJET_HOST}:{self._settings.PROXYJET_PORT}"

    def register_cached_node(self, node: ProxyNode) -> None:
        """Add or update a node in the local cache (used by SQLite mode)."""
        self._nodes_cache[node.node_id] = node

    async def report_outcome(
        self, node_id: str, success: bool, latency_ms: int, bytes_transferred: int
    ) -> None:
        """Record the outcome of a routing decision to track node performance."""
        # SQLite implementation for local testing
        if hasattr(self._settings, "USE_SQLITE") and self._settings.USE_SQLITE:
            await self._report_outcome_sqlite(node_id, success, latency_ms, bytes_transferred)
            return

        # This would handle the Supabase implementation, but we're only using SQLite for now
        return

    async def _report_outcome_sqlite(
        self, node_id: str, success: bool, latency_ms: int, bytes_transferred: int
    ) -> None:
        """Record a routing outcome using SQLite."""
        # Update the health score in our local cache
        if node_id in self._nodes_cache:
            if success:
                # Slightly increase health score for successful requests
                self._node_health[node_id] = min(1.0, self._node_health.get(node_id, 0.9) + 0.1)
            else:
                # Significantly decrease health score for failed requests
                self._node_health[node_id] = max(0.1, self._node_health.get(node_id, 0.5) - 0.3)

            # Update the node health score
            self._nodes_cache[node_id].health_score = self._node_health[node_id]

        # In a real implementation, this would write to the database
