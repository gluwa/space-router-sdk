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
    async def test_select_node_network_error(self, settings, mock_api):
        mock_api.get("http://coordination.test/internal/route/select").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        async with httpx.AsyncClient() as client:
            router = NodeRouter(client, settings)
            result = await router.select_node()

        assert result is None

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
