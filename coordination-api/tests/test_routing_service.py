"""Tests for the routing service (Bright Data fallback and node selection)."""

import os

import httpx
import pytest

from app.config import Settings
from app.services.routing_service import ProxyNode, RoutingService, _region_to_country


# ---------------------------------------------------------------------------
# _region_to_country helper
# ---------------------------------------------------------------------------


class TestRegionToCountry:
    def test_lowercase_passthrough(self):
        assert _region_to_country("us") == "us"

    def test_uppercase_lowered(self):
        assert _region_to_country("US") == "us"

    def test_mixed_case(self):
        assert _region_to_country("Kr") == "kr"


# ---------------------------------------------------------------------------
# _get_brightdata_fallback
# ---------------------------------------------------------------------------


class TestGetBrightdataFallback:
    def test_us_region_returns_country_us(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = service._get_brightdata_fallback(region="US")

        assert node is not None
        assert node.node_id == "brightdata-fallback"
        assert "-country-us" in node.endpoint_url
        assert "brd-customer-C12345-zone-residential" in node.endpoint_url

    def test_de_region_returns_country_de(self):
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = service._get_brightdata_fallback(region="DE")

        assert node is not None
        assert "-country-de" in node.endpoint_url

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
    async def test_returns_brightdata_fallback_when_no_db_and_cache_empty(self):
        """SQLite mode with no db and empty cache -> Bright Data fallback."""
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        result = await service.select_node()

        assert result is not None
        assert result.node_id == "brightdata-fallback"

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
        """select_node(region='US') falls back to Bright Data with -country-us."""
        settings = Settings(
            USE_SQLITE=False,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        result = await service.select_node(region="US")

        assert result is not None
        assert result.node_id == "brightdata-fallback"
        assert "-country-us" in result.endpoint_url

    @pytest.mark.asyncio
    async def test_select_node_with_region_sqlite_empty_cache(self):
        """SQLite mode, empty cache, region hint -> Bright Data with geo-targeting."""
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        result = await service.select_node(region="US")

        assert result is not None
        assert result.node_id == "brightdata-fallback"
        assert "-country-us" in result.endpoint_url


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

        # Manually seed a node into the in-memory cache
        test_node = ProxyNode(
            node_id="test-node-1",
            endpoint_url="http://127.0.0.1:9090",
            health_score=1.0,
        )
        service._nodes_cache["test-node-1"] = test_node
        service._node_health["test-node-1"] = 1.0

        # Report a failure -> health decreases
        await service.report_outcome("test-node-1", False, 50, 512)
        assert service._nodes_cache["test-node-1"].health_score < 1.0


# ---------------------------------------------------------------------------
# Fallback precedence
# ---------------------------------------------------------------------------


class TestFallbackPrecedence:
    @pytest.mark.asyncio
    async def test_prefers_cached_home_node_over_brightdata(self):
        """When a home node exists in cache, it is selected over Bright Data."""
        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings)

        # Seed a home node
        service._nodes_cache["home-1"] = ProxyNode(
            node_id="home-1",
            endpoint_url="http://192.168.1.10:9090",
            health_score=1.0,
        )

        result = await service.select_node()
        assert result is not None
        assert result.node_id == "home-1"

    @pytest.mark.asyncio
    async def test_selects_node_from_sqlite_db(self, tmp_path):
        """When an online node exists in the SQLite database, it is selected."""
        from app.sqlite_db import SQLiteClient

        db_path = str(tmp_path / "test.db")
        db = SQLiteClient(db_path)
        await db.insert("nodes", {
            "id": "db-node-1",
            "endpoint_url": "http://10.0.0.1:9090",
            "connectivity_type": "direct",
            "node_type": "residential",
            "status": "online",
            "health_score": 1.0,
        })

        settings = Settings(
            USE_SQLITE=True,
            BRIGHTDATA_ACCOUNT_ID="C12345",
            BRIGHTDATA_ZONE="residential",
            BRIGHTDATA_PASSWORD="pass",
        )
        service = RoutingService(httpx.AsyncClient(), settings, db=db)
        result = await service.select_node()

        assert result is not None
        assert result.node_id == "db-node-1"


# ---------------------------------------------------------------------------
# Live Bright Data integration (requires real credentials)
# ---------------------------------------------------------------------------

_BD_ACCOUNT = os.environ.get("SR_BRIGHTDATA_ACCOUNT_ID", "")
_BD_ZONE = os.environ.get("SR_BRIGHTDATA_ZONE", "")
_BD_PASS = os.environ.get("SR_BRIGHTDATA_PASSWORD", "")
_BD_CA_CERT = os.environ.get("SR_BRIGHTDATA_CA_CERT", "")
_has_bd_creds = bool(_BD_ACCOUNT and _BD_ZONE and _BD_PASS)


def _bd_ssl_verify():
    """Return the verify argument for httpx: SSLContext with BD CA, or False.

    Python 3.14 enables strict X.509 checks by default, which rejects the
    Bright Data root CA (missing Authority Key Identifier extension — valid
    per RFC 5280 for self-signed roots).  We create a context with strict
    mode relaxed so the cert is accepted.
    """
    import ssl

    if not (_BD_CA_CERT and os.path.isfile(_BD_CA_CERT)):
        return False

    ctx = ssl.create_default_context(cafile=_BD_CA_CERT)
    # Relax Python 3.14's strict X.509 flag so the root CA's missing
    # Authority Key Identifier extension does not cause a rejection.
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


@pytest.mark.skipif(not _has_bd_creds, reason="Bright Data credentials not set")
class TestBrightDataLive:
    """Smoke tests that hit the real Bright Data proxy.

    Skipped unless SR_BRIGHTDATA_ACCOUNT_ID, SR_BRIGHTDATA_ZONE, and
    SR_BRIGHTDATA_PASSWORD are set in the environment.

    Set SR_BRIGHTDATA_CA_CERT to the path of the Bright Data CA certificate
    (PEM) to enable proper TLS verification.  Without it the tests fall back
    to verify=False.
    """

    @pytest.mark.asyncio
    async def test_http_request_through_brightdata(self):
        """Make a real HTTP request through Bright Data and verify it succeeds."""
        settings = Settings(
            USE_SQLITE=False,
            BRIGHTDATA_ACCOUNT_ID=_BD_ACCOUNT,
            BRIGHTDATA_ZONE=_BD_ZONE,
            BRIGHTDATA_PASSWORD=_BD_PASS,
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = await service.select_node()

        assert node is not None
        assert node.node_id == "brightdata-fallback"

        # Use the Bright Data CA cert when available; fall back to verify=False
        async with httpx.AsyncClient(
            proxy=node.endpoint_url, verify=_bd_ssl_verify(), timeout=30.0
        ) as client:
            resp = await client.get("https://lumtest.com/myip.json")

        assert resp.status_code == 200
        data = resp.json()
        # lumtest.com/myip.json returns geo info including "country" and "ip_version"
        assert "country" in data

    @pytest.mark.asyncio
    async def test_brightdata_with_geo_targeting(self):
        """Verify geo-targeted request routes through the expected country."""
        settings = Settings(
            USE_SQLITE=False,
            BRIGHTDATA_ACCOUNT_ID=_BD_ACCOUNT,
            BRIGHTDATA_ZONE=_BD_ZONE,
            BRIGHTDATA_PASSWORD=_BD_PASS,
        )
        service = RoutingService(httpx.AsyncClient(), settings)
        node = await service.select_node(region="us")

        assert node is not None
        assert "-country-us" in node.endpoint_url

        async with httpx.AsyncClient(
            proxy=node.endpoint_url, verify=_bd_ssl_verify(), timeout=30.0
        ) as client:
            resp = await client.get("https://lumtest.com/myip.json")

        assert resp.status_code == 200
        data = resp.json()
        assert "country" in data
        assert data["country"].upper() == "US"
