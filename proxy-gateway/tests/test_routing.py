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
    async def test_select_node_network_error_returns_none(self, settings, mock_api):
        """Network errors return None (no local fallback in gateway)."""
        mock_api.get("http://coordination.test/internal/route/select").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        async with httpx.AsyncClient() as client:
            router = NodeRouter(client, settings)
            result = await router.select_node()

        assert result is None

    @pytest.mark.asyncio
    async def test_select_node_forwards_region_and_node_type_as_query_params(self, settings, mock_api):
        """region and node_type should be sent as query params to coordination API."""
        route = mock_api.get("http://coordination.test/internal/route/select").respond(
            200,
            json={"node_id": "us-res", "endpoint_url": "https://10.0.0.1:9090"},
        )

        async with httpx.AsyncClient() as client:
            router = NodeRouter(client, settings)
            result = await router.select_node(region="US", node_type="residential")

        assert result is not None
        assert result.node_id == "us-res"

        # Verify query params were sent
        req = route.calls[0].request
        assert "region=US" in str(req.url)
        assert "node_type=residential" in str(req.url)

    @pytest.mark.asyncio
    async def test_select_node_omits_query_params_when_none(self, settings, mock_api):
        """Without filters, no region/node_type query params should be sent."""
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
        assert "region" not in str(req.url)
        assert "node_type" not in str(req.url)

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
