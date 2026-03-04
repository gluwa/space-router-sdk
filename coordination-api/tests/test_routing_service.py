"""Tests for the routing service (node selection and health scoring)."""

import httpx
import pytest

from app.config import Settings
from app.services.routing_service import ProxyNode, RoutingService


class TestProxyjetEndpointUrl:
    def test_builds_correct_url(self):
        settings = Settings(
            USE_SQLITE=False,
            PROXYJET_HOST="proxy.proxyjet.io",
            PROXYJET_PORT=8080,
            PROXYJET_USERNAME="user",
            PROXYJET_PASSWORD="pass",
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)
        url = service._proxyjet_endpoint_url("user:pass")
        assert url == "http://user:pass@proxy.proxyjet.io:8080"


class TestSelectNode:
    @pytest.mark.asyncio
    async def test_selects_sqlite_node(self, tmp_path):
        settings = Settings(
            USE_SQLITE=True,
            SQLITE_DB_PATH=str(tmp_path / "test.db"),
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)
        result = await service.select_node()

        assert result is not None
        assert result.node_id != ""
        assert result.endpoint_url != ""

    @pytest.mark.asyncio
    async def test_fallback_to_proxyjet_when_not_sqlite(self):
        settings = Settings(
            USE_SQLITE=False,
            PROXYJET_HOST="proxy.proxyjet.io",
            PROXYJET_PORT=8080,
            PROXYJET_USERNAME="user",
            PROXYJET_PASSWORD="pass",
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)
        result = await service.select_node()

        assert result is not None
        assert result.node_id == "proxyjet-fallback"
        assert "proxy.proxyjet.io" in result.endpoint_url

    @pytest.mark.asyncio
    async def test_returns_none_when_no_nodes_and_no_proxyjet(self):
        settings = Settings(
            USE_SQLITE=False,
            PROXYJET_HOST="",
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)
        result = await service.select_node()

        assert result is None


class TestSelectNodeFiltering:
    @pytest.mark.asyncio
    async def test_filter_by_ip_type(self, tmp_path):
        settings = Settings(
            USE_SQLITE=True,
            SQLITE_DB_PATH=str(tmp_path / "test.db"),
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)

        # Register nodes with different ip_types
        service.register_cached_node(ProxyNode(
            node_id="residential-1",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))
        service.register_cached_node(ProxyNode(
            node_id="datacenter-1",
            endpoint_url="https://10.0.0.2:9090",
            health_score=1.0,
            ip_type="datacenter",
            ip_region="Ashburn, US",
        ))

        # Request residential
        result = await service.select_node(ip_type="residential")
        assert result is not None
        assert result.node_id == "residential-1"
        assert result.ip_type == "residential"

        # Request datacenter
        result = await service.select_node(ip_type="datacenter")
        assert result is not None
        assert result.node_id == "datacenter-1"
        assert result.ip_type == "datacenter"

    @pytest.mark.asyncio
    async def test_filter_by_ip_region(self, tmp_path):
        settings = Settings(
            USE_SQLITE=True,
            SQLITE_DB_PATH=str(tmp_path / "test.db"),
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)

        service.register_cached_node(ProxyNode(
            node_id="kr-node",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))
        service.register_cached_node(ProxyNode(
            node_id="us-node",
            endpoint_url="https://10.0.0.2:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Ashburn, US",
        ))

        # Request Seoul region (substring match, case-insensitive)
        result = await service.select_node(ip_region="Seoul")
        assert result is not None
        assert result.node_id == "kr-node"

        # Request US region
        result = await service.select_node(ip_region="US")
        assert result is not None
        assert result.node_id == "us-node"

    @pytest.mark.asyncio
    async def test_filter_by_ip_type_and_region(self, tmp_path):
        settings = Settings(
            USE_SQLITE=True,
            SQLITE_DB_PATH=str(tmp_path / "test.db"),
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)

        service.register_cached_node(ProxyNode(
            node_id="kr-residential",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))
        service.register_cached_node(ProxyNode(
            node_id="kr-datacenter",
            endpoint_url="https://10.0.0.2:9090",
            health_score=1.0,
            ip_type="datacenter",
            ip_region="Seoul, KR",
        ))
        service.register_cached_node(ProxyNode(
            node_id="us-residential",
            endpoint_url="https://10.0.0.3:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Ashburn, US",
        ))

        result = await service.select_node(ip_type="residential", ip_region="Seoul")
        assert result is not None
        assert result.node_id == "kr-residential"

    @pytest.mark.asyncio
    async def test_fallback_when_no_filter_match(self, tmp_path):
        """Falls back to any node when no nodes match the filter."""
        settings = Settings(
            USE_SQLITE=True,
            SQLITE_DB_PATH=str(tmp_path / "test.db"),
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)

        service.register_cached_node(ProxyNode(
            node_id="only-node",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))

        # Request a type that doesn't exist — should fall back
        result = await service.select_node(ip_type="mobile")
        assert result is not None
        assert result.node_id == "only-node"

    @pytest.mark.asyncio
    async def test_case_insensitive_region_filter(self, tmp_path):
        """Region match should be case-insensitive."""
        settings = Settings(
            USE_SQLITE=True,
            SQLITE_DB_PATH=str(tmp_path / "test.db"),
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)

        service.register_cached_node(ProxyNode(
            node_id="kr-node",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))
        service.register_cached_node(ProxyNode(
            node_id="us-node",
            endpoint_url="https://10.0.0.2:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Ashburn, US",
        ))

        # Lowercase "seoul" should match "Seoul, KR"
        result = await service.select_node(ip_region="seoul")
        assert result is not None
        assert result.node_id == "kr-node"

        # Lowercase "kr" should match "Seoul, KR"
        result = await service.select_node(ip_region="kr")
        assert result is not None
        assert result.node_id == "kr-node"

    @pytest.mark.asyncio
    async def test_node_with_empty_ip_region_skipped_by_filter(self, tmp_path):
        """Nodes with empty ip_region don't match region filters."""
        settings = Settings(
            USE_SQLITE=True,
            SQLITE_DB_PATH=str(tmp_path / "test.db"),
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)

        service.register_cached_node(ProxyNode(
            node_id="no-region",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="",
        ))
        service.register_cached_node(ProxyNode(
            node_id="kr-node",
            endpoint_url="https://10.0.0.2:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))

        result = await service.select_node(ip_region="Seoul")
        assert result is not None
        assert result.node_id == "kr-node"

    @pytest.mark.asyncio
    async def test_empty_string_filter_treated_as_no_filter(self, tmp_path):
        """Empty string ip_type/ip_region should not filter (same as None)."""
        settings = Settings(
            USE_SQLITE=True,
            SQLITE_DB_PATH=str(tmp_path / "test.db"),
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)

        service.register_cached_node(ProxyNode(
            node_id="node-a",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))

        # Empty strings should behave like None (no filtering)
        result = await service.select_node(ip_type="", ip_region="")
        assert result is not None
        assert result.node_id == "node-a"


class TestReportOutcome:
    @pytest.mark.asyncio
    async def test_records_outcome_sqlite(self, tmp_path):
        settings = Settings(
            USE_SQLITE=True,
            SQLITE_DB_PATH=str(tmp_path / "test.db"),
        )
        http_client = httpx.AsyncClient()
        service = RoutingService(http_client, settings)

        # First select a node (populates cache)
        node = await service.select_node()
        assert node is not None

        # Report a successful outcome
        await service.report_outcome(node.node_id, True, 100, 1024)
        # Should not raise
