"""Tests for the routing service (Bright Data fallback and node selection)."""

import httpx
import pytest

from app.config import Settings
from app.services.routing_service import ProxyNode, RoutingService, _region_to_country


# ---------------------------------------------------------------------------
# _region_to_country helper
# ---------------------------------------------------------------------------


class TestRegionToCountry:
    def test_bare_iso_code(self):
        assert _region_to_country("us") == "us"

    def test_compound_region(self):
        assert _region_to_country("us-west") == "us"

    def test_eu_central(self):
        assert _region_to_country("eu-central") == "de"

    def test_unknown_returns_none(self):
        assert _region_to_country("unknown-region") is None

    def test_case_insensitive(self):
        assert _region_to_country("US") == "us"
        assert _region_to_country("EU-CENTRAL") == "de"


# ---------------------------------------------------------------------------
# _get_brightdata_fallback
# ---------------------------------------------------------------------------


class TestGetBrightdataFallback:
    def test_us_west_returns_country_us(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = service._get_brightdata_fallback(region="us-west")

        assert node is not None
        assert node.node_id == "brightdata-fallback"
        assert "-country-us" in node.endpoint_url
        assert "brd-customer-C12345-zone-residential" in node.endpoint_url

    def test_eu_central_returns_country_de(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = service._get_brightdata_fallback(region="eu-central")

        assert node is not None
        assert "-country-de" in node.endpoint_url

    def test_unknown_region_no_country_suffix(self):
        """Unknown region -> no crash, no country suffix, still returns a node."""
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = service._get_brightdata_fallback(region="unknown-region")

        assert node is not None
        assert "-country-" not in node.endpoint_url
        assert "brd-customer-C12345-zone-residential" in node.endpoint_url

    def test_returns_none_when_account_id_empty(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        assert service._get_brightdata_fallback() is None

    def test_returns_none_when_zone_empty(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        assert service._get_brightdata_fallback() is None

    def test_returns_none_when_password_empty(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        assert service._get_brightdata_fallback() is None

    def test_no_region_no_country_suffix(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = service._get_brightdata_fallback(region=None)

        assert node is not None
        assert "-country-" not in node.endpoint_url

    def test_health_score_is_one(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = service._get_brightdata_fallback()
        assert node.health_score == 1.0

    def test_endpoint_url_format(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="res_zone",
            BRIGHTDATA_PASSWORD="s3cret",
            BRIGHTDATA_HOST="brd.superproxy.io",
            BRIGHTDATA_PORT=33335,
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = service._get_brightdata_fallback()
        assert node.endpoint_url == "http://brd-customer-C12345-zone-res_zone:s3cret@brd.superproxy.io:33335"


# ---------------------------------------------------------------------------
# select_node
# ---------------------------------------------------------------------------


class TestSelectNode:
    @pytest.mark.asyncio
    async def test_returns_local_test_node_when_cache_empty(self):
        """SQLite mode with empty cache seeds a local test node."""
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        result = await service.select_node()

        assert result is not None
        assert result.node_id == "local-test-node-id"

    @pytest.mark.asyncio
    async def test_falls_back_to_brightdata_when_supabase_and_no_home_nodes(self):
        """Non-SQLite mode (Supabase stub) -> falls back to Bright Data."""
        settings = Settings(
            USE_SQLITE=False,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        result = await service.select_node()

        assert result is not None
        assert result.node_id == "brightdata-fallback"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_nodes_and_no_brightdata(self):
        """No home nodes + no Bright Data config -> None (503)."""
        settings = Settings(
            USE_SQLITE=False,
            BRIGHTDATA_ACCOUNT_ID="",
            BRIGHTDATA_ZONE="",
            BRIGHTDATA_PASSWORD="",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        result = await service.select_node()

        assert result is None

    @pytest.mark.asyncio
    async def test_brightdata_fallback_with_region(self):
        """select_node(region='us-west') falls back to Bright Data with -country-us."""
        settings = Settings(
            USE_SQLITE=False,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        result = await service.select_node(region="us-west")

        assert result is not None
        assert result.node_id == "brightdata-fallback"
        assert "-country-us" in result.endpoint_url

    @pytest.mark.asyncio
    async def test_select_node_with_region_sqlite_empty_cache(self):
        """SQLite mode, empty cache, region hint -> seeds local test node (region filter
        is a pass-through in _node_matches_region for now)."""
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        result = await service.select_node(region="us-west")

        assert result is not None
        # Seeds local-test-node-id because cache is empty
        assert result.node_id == "local-test-node-id"


# ---------------------------------------------------------------------------
# report_outcome
# ---------------------------------------------------------------------------


class TestReportOutcome:
    @pytest.mark.asyncio
    async def test_skips_brightdata_fallback(self):
        """report_outcome does not crash when node_id is brightdata-fallback."""
        settings = Settings(USE_SQLITE=True)
        service = RoutingService(httpx.AsyncClient(), settings)
        # Should not raise
        await service.report_outcome("brightdata-fallback", True, 100, 1024)

    @pytest.mark.asyncio
    async def test_updates_health_for_cached_node(self):
        settings = Settings(USE_SQLITE=True)
        service = RoutingService(httpx.AsyncClient(), settings)

        # Seed a node into cache
        node = await service.select_node()
        assert node is not None

        # Report a failure -> health decreases
        await service.report_outcome(node.node_id, False, 50, 512)
        assert service._nodes_cache[node.node_id].health_score < 1.0
