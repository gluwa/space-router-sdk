import httpx
import pytest
import respx

from app.routing import NodeRouter, NodeSelection


class TestNodeRouter:
    @pytest.mark.asyncio
    async def test_select_node_success(self, settings, mock_api):
        mock_api.get("http://coordination.test/internal/route/select").respond(
            200,
            json={"node_id": "node-abc", "endpoint_url": "https://node1.example.com:8443"},
        )

        async with httpx.AsyncClient() as client:
            router = NodeRouter(client, settings)
            result = await router.select_node()

        assert result is not None
        assert result.node_id == "node-abc"
        assert result.endpoint_url == "https://node1.example.com:8443"

    @pytest.mark.asyncio
    async def test_select_node_no_nodes(self, settings, mock_api):
        mock_api.get("http://coordination.test/internal/route/select").respond(503)

        async with httpx.AsyncClient() as client:
            router = NodeRouter(client, settings)
            result = await router.select_node()

        assert result is None

    @pytest.mark.asyncio
    async def test_select_node_network_error_sqlite_fallback(self, settings, mock_api):
        """In SQLite mode, network errors fall back to a local test node."""
        mock_api.get("http://coordination.test/internal/route/select").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        async with httpx.AsyncClient() as client:
            router = NodeRouter(client, settings)
            result = await router.select_node()

        # SQLite mode provides a fallback node
        assert result is not None
        assert result.node_id == "local-test-node-id"
        assert result.endpoint_url == "http://127.0.0.1:9090"

    @pytest.mark.asyncio
    async def test_select_node_forwards_ip_type_and_region_as_query_params(self, settings, mock_api):
        """ip_type and ip_region should be sent as query params to coordination API."""
        route = mock_api.get("http://coordination.test/internal/route/select").respond(
            200,
            json={"node_id": "kr-res", "endpoint_url": "https://10.0.0.1:9090"},
        )

        async with httpx.AsyncClient() as client:
            router = NodeRouter(client, settings)
            result = await router.select_node(ip_type="residential", ip_region="Seoul, KR")

        assert result is not None
        assert result.node_id == "kr-res"

        # Verify query params were sent
        req = route.calls[0].request
        assert "ip_type=residential" in str(req.url)
        assert "ip_region=" in str(req.url)
        assert "Seoul" in str(req.url)

    @pytest.mark.asyncio
    async def test_select_node_omits_query_params_when_none(self, settings, mock_api):
        """Without filters, no ip_type/ip_region query params should be sent."""
        route = mock_api.get("http://coordination.test/internal/route/select").respond(
            200,
            json={"node_id": "any-node", "endpoint_url": "https://10.0.0.1:9090"},
        )

        async with httpx.AsyncClient() as client:
            router = NodeRouter(client, settings)
            result = await router.select_node()

        assert result is not None

        # Verify no filter query params were sent
        req = route.calls[0].request
        assert "ip_type" not in str(req.url)
        assert "ip_region" not in str(req.url)

    @pytest.mark.asyncio
    async def test_report_outcome(self, settings, mock_api):
        route = mock_api.post("http://coordination.test/internal/route/report").respond(200)

        async with httpx.AsyncClient() as client:
            router = NodeRouter(client, settings)
            router.report_outcome("node-abc", True, 150, 4096)
            # Give the fire-and-forget task time to run
            import asyncio
            await asyncio.sleep(0.1)

        assert route.call_count == 1
