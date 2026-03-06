"""Routing service for selecting nodes and tracking outcomes."""

import logging
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Maps Space Router region prefixes to ISO-3166-1 alpha-2 country codes used
# by Bright Data's username targeting parameter (-country-XX).
# Extend this table as new regions are registered by home node operators.
_REGION_TO_COUNTRY: dict[str, str] = {
    "us": "us",
    "eu": "de",
    "ap": "jp",
    "au": "au",
    "ca": "ca",
    "gb": "gb",
    "uk": "gb",
    "de": "de",
    "fr": "fr",
    "jp": "jp",
    "sg": "sg",
    "br": "br",
    "in": "in",
}


def _region_to_country(region: str) -> str | None:
    """Derive a Bright Data country code from a Space Router region string.

    Accepts either a bare ISO code (``"us"``) or a compound region string
    (``"us-west"``, ``"eu-central"``).  Returns ``None`` if no mapping found.
    """
    region = region.lower().strip()
    # Try exact match first
    if region in _REGION_TO_COUNTRY:
        return _REGION_TO_COUNTRY[region]
    # Try prefix (e.g. "us-west" -> "us")
    prefix = region.split("-")[0]
    return _REGION_TO_COUNTRY.get(prefix)


@dataclass
class ProxyNode:
    """Data class for a proxy node."""

    node_id: str
    endpoint_url: str
    health_score: float


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
        region: str | None = None,
        node_type: str | None = None,
    ) -> Optional[ProxyNode]:
        """Select the best available node for routing traffic.

        Tries home nodes first (filtered by *region* and *node_type* when
        provided), then falls back to Bright Data if no matching node is found.
        """
        if hasattr(self._settings, "USE_SQLITE") and self._settings.USE_SQLITE:
            node = await self._select_node_sqlite(region=region, node_type=node_type)
        else:
            node = await self._select_node_supabase(region=region, node_type=node_type)

        if node:
            return node

        # No matching home node — fall back to Bright Data
        return self._get_brightdata_fallback(region=region)

    async def _select_node_sqlite(
        self,
        region: str | None = None,
        node_type: str | None = None,
    ) -> Optional[ProxyNode]:
        """Select a node using the in-memory SQLite cache."""
        candidates = list(self._nodes_cache.values())

        # Filter by region and type if requested
        if region:
            candidates = [n for n in candidates if _node_matches_region(n, region)]
        if node_type:
            candidates = [n for n in candidates if _node_matches_type(n, node_type)]

        if candidates:
            # Weighted random selection by health score
            weights = [max(c.health_score, 0.01) for c in candidates]
            return random.choices(candidates, weights=weights, k=1)[0]

        # No cached nodes match — seed a local test node for development
        node = ProxyNode(
            node_id="local-test-node-id",
            endpoint_url="http://127.0.0.1:9090",
            health_score=1.0,
        )
        self._nodes_cache[node.node_id] = node
        return node

    async def _select_node_supabase(
        self,
        region: str | None = None,
        node_type: str | None = None,
    ) -> Optional[ProxyNode]:
        """Select a node from Supabase (production path — stub for now)."""
        return None

    def _get_brightdata_fallback(self, region: str | None = None) -> Optional[ProxyNode]:
        """Build a Bright Data proxy endpoint, optionally geo-targeted.

        Returns ``None`` if Bright Data is not configured.
        """
        s = self._settings
        if not s.BRIGHTDATA_ACCOUNT_ID or not s.BRIGHTDATA_ZONE or not s.BRIGHTDATA_PASSWORD:
            return None

        username = f"brd-customer-{s.BRIGHTDATA_ACCOUNT_ID}-zone-{s.BRIGHTDATA_ZONE}"

        if region:
            country_code = _region_to_country(region)
            if country_code:
                username += f"-country-{country_code}"
                logger.debug("Bright Data fallback with country targeting: %s", country_code)
            else:
                logger.warning(
                    "No country mapping for region %r — Bright Data fallback will not geo-target",
                    region,
                )

        endpoint_url = f"http://{username}:{s.BRIGHTDATA_PASSWORD}@{s.BRIGHTDATA_HOST}:{s.BRIGHTDATA_PORT}"

        return ProxyNode(
            node_id="brightdata-fallback",
            endpoint_url=endpoint_url,
            health_score=1.0,
        )

    async def report_outcome(
        self,
        node_id: str,
        success: bool,
        latency_ms: int,
        bytes_transferred: int,
    ) -> None:
        """Record the outcome of a routing decision to track node performance."""
        if node_id == "brightdata-fallback":
            # Don't track health for the managed fallback
            return

        if hasattr(self._settings, "USE_SQLITE") and self._settings.USE_SQLITE:
            await self._report_outcome_sqlite(node_id, success, latency_ms, bytes_transferred)

    async def _report_outcome_sqlite(
        self,
        node_id: str,
        success: bool,
        latency_ms: int,
        bytes_transferred: int,
    ) -> None:
        """Update a node's health score in the local cache."""
        if node_id not in self._nodes_cache:
            return

        current = self._node_health.get(node_id, 1.0)
        if success:
            self._node_health[node_id] = min(1.0, current + 0.1)
        else:
            self._node_health[node_id] = max(0.1, current - 0.3)

        self._nodes_cache[node_id].health_score = self._node_health[node_id]


# ---------------------------------------------------------------------------
# Node-matching helpers (extend once Supabase carries these fields)
# ---------------------------------------------------------------------------

def _node_matches_region(node: ProxyNode, region: str) -> bool:
    """Return True if *node* is compatible with the requested *region*.

    Nodes don't yet carry region metadata in the local cache, so this always
    returns True for now — the Supabase path will query by region directly.
    """
    return True


def _node_matches_type(node: ProxyNode, node_type: str) -> bool:
    """Return True if *node* matches the requested *node_type*."""
    return True
