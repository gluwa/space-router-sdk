"""Tests for the internal endpoints (proxy-gateway contract)."""

import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.services.auth_service import AuthService
from app.services.ip_info_service import IPInfoService
from app.services.routing_service import RoutingService
from app.sqlite_db import SQLiteClient


def _setup_app(settings: Settings) -> TestClient:
    """Wire up the app with test dependencies."""
    http_client = httpx.AsyncClient()
    db = SQLiteClient(settings.SQLITE_DB_PATH)
    app.state.settings = settings
    app.state.http_client = http_client
    app.state.db = db
    app.state.auth_service = AuthService(http_client, settings, db)
    app.state.ip_info_service = IPInfoService(http_client, settings.IPINFO_TOKEN)
    app.state.routing_service = RoutingService(http_client, settings, db)

    # Override cached settings so verify_internal_secret uses our test settings
    get_settings.cache_clear()
    import app.config as config_module
    config_module.get_settings = lambda: settings

    return TestClient(app, raise_server_exceptions=False)


class TestAuthValidate:
    def test_valid_key(self, settings):
        """SQLite auth validates keys against the database."""
        client = _setup_app(settings)

        # Insert an API key directly via sqlite3 (sync) so validation succeeds
        conn = sqlite3.connect(settings.SQLITE_DB_PATH)
        conn.execute(
            "INSERT INTO api_keys (id, name, key_hash, key_prefix, rate_limit_rpm, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            ("test-key-id", "test-key", "abc123hash", "sr_live_test", 60, 1),
        )
        conn.commit()
        conn.close()

        resp = client.post(
            "/internal/auth/validate",
            json={"key_hash": "abc123hash"},
            headers={"X-Internal-API-Key": settings.INTERNAL_API_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["api_key_id"] is not None
        assert data["rate_limit_rpm"] is not None

    def test_missing_auth_header(self, settings):
        client = _setup_app(settings)
        resp = client.post(
            "/internal/auth/validate",
            json={"key_hash": "abc123hash"},
        )
        assert resp.status_code == 403  # APIKeyHeader missing

    def test_wrong_auth_secret_rejected_in_production_mode(self):
        """Non-SQLite mode rejects wrong auth secrets."""
        prod_settings = Settings(
            PORT=8000,
            INTERNAL_API_SECRET="test-secret",
            USE_SQLITE=False,
        )
        get_settings.cache_clear()
        # Patch in both modules so the dependency picks it up
        import app.config as config_module
        import app.dependencies as deps_module
        original = deps_module.get_settings
        config_module.get_settings = lambda: prod_settings
        deps_module.get_settings = lambda: prod_settings

        http_client = httpx.AsyncClient()
        app.state.settings = prod_settings
        app.state.http_client = http_client
        app.state.auth_service = AuthService(http_client, prod_settings)
        app.state.ip_info_service = IPInfoService(http_client, "")
        app.state.routing_service = RoutingService(http_client, prod_settings)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/internal/auth/validate",
            json={"key_hash": "abc123hash"},
            headers={"X-Internal-API-Key": "wrong-secret"},
        )
        assert resp.status_code == 403

        # Restore
        deps_module.get_settings = original


class TestRouteSelect:
    def test_selects_local_node(self, settings):
        """SQLite mode selects a node from the database."""
        client = _setup_app(settings)

        # Insert a test node directly via sqlite3
        conn = sqlite3.connect(settings.SQLITE_DB_PATH)
        conn.execute(
            "INSERT INTO nodes (id, endpoint_url, public_ip, connectivity_type, status, health_score, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("test-node", "https://127.0.0.1:9090", "127.0.0.1", "direct", "online", 1.0),
        )
        conn.commit()
        conn.close()

        resp = client.get(
            "/internal/route/select",
            headers={"X-Internal-API-Key": settings.INTERNAL_API_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] != ""
        assert data["endpoint_url"] != ""

    def test_no_nodes_no_proxyjet(self):
        """No proxyjet configured and non-SQLite mode -> 503."""
        no_proxyjet_settings = Settings(
            PORT=8000,
            INTERNAL_API_SECRET="test-secret",
            USE_SQLITE=False,
            PROXYJET_HOST="",  # Not configured
        )

        get_settings.cache_clear()
        import app.config as config_module
        config_module.get_settings = lambda: no_proxyjet_settings

        http_client = httpx.AsyncClient()
        app.state.settings = no_proxyjet_settings
        app.state.http_client = http_client
        app.state.auth_service = AuthService(http_client, no_proxyjet_settings)
        app.state.ip_info_service = IPInfoService(http_client, "")
        app.state.routing_service = RoutingService(http_client, no_proxyjet_settings)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/internal/route/select",
            headers={"X-Internal-API-Key": no_proxyjet_settings.INTERNAL_API_SECRET},
        )
        assert resp.status_code == 503


class TestRouteSelectFiltering:
    """Verify ip_type and ip_region query params are forwarded to the routing service."""

    def test_select_with_ip_type_param(self, settings):
        client = _setup_app(settings)

        # Register nodes with different ip_types via the routing service
        routing_svc: RoutingService = app.state.routing_service
        from app.services.routing_service import ProxyNode
        routing_svc.register_cached_node(ProxyNode(
            node_id="residential-node",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))
        routing_svc.register_cached_node(ProxyNode(
            node_id="dc-node",
            endpoint_url="https://10.0.0.2:9090",
            health_score=1.0,
            ip_type="datacenter",
            ip_region="Ashburn, US",
        ))

        resp = client.get(
            "/internal/route/select",
            params={"ip_type": "residential"},
            headers={"X-Internal-API-Key": settings.INTERNAL_API_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == "residential-node"

    def test_select_with_ip_region_param(self, settings):
        client = _setup_app(settings)

        routing_svc: RoutingService = app.state.routing_service
        from app.services.routing_service import ProxyNode
        routing_svc.register_cached_node(ProxyNode(
            node_id="kr-node",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))
        routing_svc.register_cached_node(ProxyNode(
            node_id="us-node",
            endpoint_url="https://10.0.0.2:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Ashburn, US",
        ))

        resp = client.get(
            "/internal/route/select",
            params={"ip_region": "Seoul"},
            headers={"X-Internal-API-Key": settings.INTERNAL_API_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == "kr-node"

    def test_select_with_both_params(self, settings):
        client = _setup_app(settings)

        routing_svc: RoutingService = app.state.routing_service
        from app.services.routing_service import ProxyNode
        routing_svc.register_cached_node(ProxyNode(
            node_id="kr-residential",
            endpoint_url="https://10.0.0.1:9090",
            health_score=1.0,
            ip_type="residential",
            ip_region="Seoul, KR",
        ))
        routing_svc.register_cached_node(ProxyNode(
            node_id="kr-datacenter",
            endpoint_url="https://10.0.0.2:9090",
            health_score=1.0,
            ip_type="datacenter",
            ip_region="Seoul, KR",
        ))

        resp = client.get(
            "/internal/route/select",
            params={"ip_type": "datacenter", "ip_region": "Seoul"},
            headers={"X-Internal-API-Key": settings.INTERNAL_API_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == "kr-datacenter"


class TestRouteReport:
    def test_report_success(self, settings):
        client = _setup_app(settings)
        resp = client.post(
            "/internal/route/report",
            json={
                "node_id": "node-abc",
                "success": True,
                "latency_ms": 150,
                "bytes": 4096,
            },
            headers={"X-Internal-API-Key": settings.INTERNAL_API_SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
