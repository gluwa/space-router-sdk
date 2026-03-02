import logging
import random
from dataclasses import dataclass
from urllib.parse import quote

from app.config import Settings
from app.db import SupabaseClient

logger = logging.getLogger(__name__)


@dataclass
class NodeSelection:
    node_id: str
    endpoint_url: str


class RoutingService:
    def __init__(self, db: SupabaseClient, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def _build_proxyjet_endpoint_url(self) -> str:
        """Build an endpoint URL for proxyjet.io that encodes credentials.

        Format: http://user:pass@host:port
        The proxy-gateway will extract creds from this URL and send them
        as Proxy-Authorization to the upstream proxy.
        """
        s = self._settings
        user = quote(s.PROXYJET_USERNAME, safe="")
        passwd = quote(s.PROXYJET_PASSWORD, safe="")
        return f"http://{user}:{passwd}@{s.PROXYJET_HOST}:{s.PROXYJET_PORT}"

    async def select_node(self) -> NodeSelection | None:
        """Select the best available node for routing.

        Selection strategy:
        1. Query all nodes with status=online and health_score > 0.2
        2. Weight by health_score, pick randomly
        3. If no nodes found, fall back to proxyjet.io (always available)
        """
        try:
            nodes = await self._db.select(
                "nodes",
                params={
                    "status": "eq.online",
                    "health_score": "gt.0.2",
                    "select": "id,endpoint_url,health_score,node_type",
                    "order": "health_score.desc",
                },
            )
        except Exception:
            logger.exception("Failed to query nodes from database")
            nodes = []

        if not nodes:
            # Fall back to proxyjet.io if configured
            if self._settings.PROXYJET_HOST:
                return NodeSelection(
                    node_id=self._settings.PROXYJET_NODE_ID,
                    endpoint_url=self._build_proxyjet_endpoint_url(),
                )
            return None

        # Weighted random selection by health_score
        selected = _weighted_random_choice(nodes)
        return NodeSelection(
            node_id=selected["id"],
            endpoint_url=selected["endpoint_url"],
        )

    async def report_outcome(
        self,
        node_id: str,
        success: bool,
        latency_ms: int,
        bytes_transferred: int,
    ) -> None:
        """Record a routing outcome and update node health metrics."""
        try:
            await self._db.insert(
                "route_outcomes",
                {
                    "node_id": node_id,
                    "success": success,
                    "latency_ms": latency_ms,
                    "bytes_transferred": bytes_transferred,
                },
                return_rows=False,
            )
        except Exception:
            logger.warning("Failed to insert route outcome for node %s", node_id)

        # Update health score based on recent outcomes
        try:
            await self._update_health_score(node_id)
        except Exception:
            logger.warning("Failed to update health score for node %s", node_id)

    async def _update_health_score(self, node_id: str) -> None:
        """Recalculate health score from recent outcomes.

        Simple formula: success_rate over last 100 requests.
        """
        try:
            outcomes = await self._db.select(
                "route_outcomes",
                params={
                    "node_id": f"eq.{node_id}",
                    "select": "success",
                    "order": "created_at.desc",
                    "limit": "100",
                },
            )
        except Exception:
            return

        if not outcomes:
            return

        total = len(outcomes)
        successes = sum(1 for o in outcomes if o["success"])
        health_score = round(successes / total, 3)

        await self._db.update(
            "nodes",
            {"health_score": health_score},
            params={"id": f"eq.{node_id}"},
        )


def _weighted_random_choice(nodes: list[dict]) -> dict:
    """Pick a node weighted by health_score."""
    weights = [n.get("health_score", 0.5) for n in nodes]
    total = sum(weights)
    if total == 0:
        return random.choice(nodes)
    return random.choices(nodes, weights=weights, k=1)[0]
