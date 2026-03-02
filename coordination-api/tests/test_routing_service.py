"""Tests for the routing service (node selection and health scoring)."""

import httpx
import pytest
import respx

from app.config import Settings
from app.db import SupabaseClient
from app.services.routing_service import RoutingService, _weighted_random_choice


class TestProxyjetEndpointUrl:
    def test_builds_correct_url(self):
        settings = Settings(
            SUPABASE_URL="http://test",
            SUPABASE_SERVICE_KEY="key",
            PROXYJET_HOST="proxy.proxyjet.io",
            PROXYJET_PORT=8080,
            PROXYJET_USERNAME="user",
            PROXYJET_PASSWORD="pass",
        )
        http_client = httpx.AsyncClient()
        db = SupabaseClient(http_client, settings)
        service = RoutingService(db, settings)
        url = service._build_proxyjet_endpoint_url()
        assert url == "http://user:pass@proxy.proxyjet.io:8080"

    def test_url_encodes_special_chars(self):
        settings = Settings(
            SUPABASE_URL="http://test",
            SUPABASE_SERVICE_KEY="key",
            PROXYJET_HOST="proxy.proxyjet.io",
            PROXYJET_PORT=8080,
            PROXYJET_USERNAME="user@domain",
            PROXYJET_PASSWORD="p@ss:word",
        )
        http_client = httpx.AsyncClient()
        db = SupabaseClient(http_client, settings)
        service = RoutingService(db, settings)
        url = service._build_proxyjet_endpoint_url()
        assert "user%40domain" in url
        assert "p%40ss%3Aword" in url


class TestWeightedRandomChoice:
    def test_single_node(self):
        nodes = [{"id": "a", "health_score": 0.9}]
        assert _weighted_random_choice(nodes)["id"] == "a"

    def test_zero_weights_uses_uniform(self):
        nodes = [
            {"id": "a", "health_score": 0},
            {"id": "b", "health_score": 0},
        ]
        result = _weighted_random_choice(nodes)
        assert result["id"] in ("a", "b")

    def test_heavily_weighted(self):
        nodes = [
            {"id": "good", "health_score": 1.0},
            {"id": "bad", "health_score": 0.001},
        ]
        # Run multiple picks — the good node should dominate
        picks = [_weighted_random_choice(nodes)["id"] for _ in range(200)]
        assert picks.count("good") > 150


class TestSelectNode:
    @pytest.mark.asyncio
    async def test_selects_db_node(self):
        settings = Settings(
            SUPABASE_URL="http://supabase.test",
            SUPABASE_SERVICE_KEY="key",
            PROXYJET_HOST="proxy.proxyjet.io",
            PROXYJET_PORT=8080,
            PROXYJET_USERNAME="user",
            PROXYJET_PASSWORD="pass",
        )
        with respx.mock:
            respx.get("http://supabase.test/rest/v1/nodes").respond(
                200,
                json=[
                    {
                        "id": "node-1",
                        "endpoint_url": "http://10.0.0.1:8443",
                        "health_score": 0.9,
                        "node_type": "residential",
                    },
                ],
            )
            async with httpx.AsyncClient() as client:
                db = SupabaseClient(client, settings)
                service = RoutingService(db, settings)
                result = await service.select_node()

        assert result is not None
        assert result.node_id == "node-1"

    @pytest.mark.asyncio
    async def test_fallback_to_proxyjet_when_no_db_nodes(self):
        settings = Settings(
            SUPABASE_URL="http://supabase.test",
            SUPABASE_SERVICE_KEY="key",
            PROXYJET_HOST="proxy.proxyjet.io",
            PROXYJET_PORT=8080,
            PROXYJET_USERNAME="user",
            PROXYJET_PASSWORD="pass",
        )
        with respx.mock:
            respx.get("http://supabase.test/rest/v1/nodes").respond(200, json=[])
            async with httpx.AsyncClient() as client:
                db = SupabaseClient(client, settings)
                service = RoutingService(db, settings)
                result = await service.select_node()

        assert result is not None
        assert result.node_id == settings.PROXYJET_NODE_ID
        assert "proxy.proxyjet.io" in result.endpoint_url

    @pytest.mark.asyncio
    async def test_returns_none_when_no_nodes_and_no_proxyjet(self):
        settings = Settings(
            SUPABASE_URL="http://supabase.test",
            SUPABASE_SERVICE_KEY="key",
            PROXYJET_HOST="",
        )
        with respx.mock:
            respx.get("http://supabase.test/rest/v1/nodes").respond(200, json=[])
            async with httpx.AsyncClient() as client:
                db = SupabaseClient(client, settings)
                service = RoutingService(db, settings)
                result = await service.select_node()

        assert result is None


class TestReportOutcome:
    @pytest.mark.asyncio
    async def test_records_and_updates_health(self):
        settings = Settings(
            SUPABASE_URL="http://supabase.test",
            SUPABASE_SERVICE_KEY="key",
        )
        with respx.mock:
            insert_route = respx.post("http://supabase.test/rest/v1/route_outcomes").respond(201)
            respx.get("http://supabase.test/rest/v1/route_outcomes").respond(
                200,
                json=[{"success": True}, {"success": True}, {"success": False}],
            )
            update_route = respx.patch("http://supabase.test/rest/v1/nodes").respond(204)

            async with httpx.AsyncClient() as client:
                db = SupabaseClient(client, settings)
                service = RoutingService(db, settings)
                await service.report_outcome("node-1", True, 100, 1024)

        assert insert_route.call_count == 1
        assert update_route.call_count == 1
