"""Tests for the /nodes endpoints (registration, listing, IP classification)."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.config import Settings, get_settings
from app.main import app
from app.services.auth_service import AuthService
from app.services.ip_info_service import IPInfoService
from app.services.routing_service import RoutingService
from app.sqlite_db import SQLiteClient


def _setup_app(settings: Settings) -> TestClient:
    """Wire up the app with test dependencies and a fresh DB."""
    http_client = httpx.AsyncClient()
    db = SQLiteClient(settings.SQLITE_DB_PATH)
    app.state.settings = settings
    app.state.http_client = http_client
    app.state.db = db
    app.state.auth_service = AuthService(http_client, settings)
    app.state.ip_info_service = IPInfoService(http_client, settings.IPINFO_TOKEN)
    app.state.routing_service = RoutingService(http_client, settings)

    get_settings.cache_clear()
    import app.config as config_module
    config_module.get_settings = lambda: settings

    return TestClient(app, raise_server_exceptions=False)


class TestRegisterNode:
    @respx.mock
    def test_register_with_ip_classification(self, settings):
        """POST /nodes with public_ip triggers ipinfo lookup; response includes ip_type/ip_region."""
        respx.get("https://ipinfo.io/1.2.3.4/json").mock(
            return_value=Response(200, json={
                "ip": "1.2.3.4",
                "city": "Seoul",
                "country": "KR",
                "org": "AS4766 Korea Telecom",
                "company": {"type": "isp"},
                "privacy": {
                    "vpn": False,
                    "proxy": False,
                    "tor": False,
                    "relay": False,
                    "hosting": False,
                },
            })
        )

        client = _setup_app(settings)
        resp = client.post("/nodes", json={
            "endpoint_url": "https://10.0.0.1:9090",
            "node_type": "residential",
            "public_ip": "1.2.3.4",
            "connectivity_type": "direct",
        })

        assert resp.status_code == 201
        data = resp.json()
        assert data["ip_type"] == "residential"
        assert data["ip_region"] == "Seoul, KR"
        assert data["public_ip"] == "1.2.3.4"
        assert data["id"] is not None

    def test_register_without_public_ip(self, settings):
        """POST /nodes without public_ip should NOT call ipinfo; ip_type/ip_region are null."""
        client = _setup_app(settings)
        resp = client.post("/nodes", json={
            "endpoint_url": "https://10.0.0.1:9090",
            "node_type": "residential",
            "connectivity_type": "direct",
        })

        assert resp.status_code == 201
        data = resp.json()
        assert data["ip_type"] is None
        assert data["ip_region"] is None

    @respx.mock
    def test_register_with_ipinfo_failure_still_succeeds(self, settings):
        """If ipinfo.io fails, node still registers with null ip_type/ip_region."""
        respx.get("https://ipinfo.io/9.9.9.9/json").mock(
            return_value=Response(500, text="Internal Server Error")
        )

        client = _setup_app(settings)
        resp = client.post("/nodes", json={
            "endpoint_url": "https://10.0.0.2:9090",
            "node_type": "residential",
            "public_ip": "9.9.9.9",
            "connectivity_type": "direct",
        })

        assert resp.status_code == 201
        data = resp.json()
        assert data["ip_type"] is None
        assert data["ip_region"] is None
        # Node should still register successfully
        assert data["id"] is not None
        assert data["status"] == "online"


class TestListNodes:
    @respx.mock
    def test_list_includes_ip_classification(self, settings):
        """GET /nodes returns nodes with ip_type and ip_region fields."""
        respx.get("https://ipinfo.io/5.6.7.8/json").mock(
            return_value=Response(200, json={
                "ip": "5.6.7.8",
                "city": "Ashburn",
                "country": "US",
                "org": "AS14618 Amazon.com, Inc.",
                "privacy": {
                    "vpn": False, "proxy": False, "tor": False,
                    "relay": False, "hosting": True,
                },
            })
        )

        client = _setup_app(settings)

        # Register a node first
        client.post("/nodes", json={
            "endpoint_url": "https://10.0.0.5:9090",
            "node_type": "residential",
            "public_ip": "5.6.7.8",
            "connectivity_type": "direct",
        })

        # List nodes
        resp = client.get("/nodes")
        assert resp.status_code == 200
        nodes = resp.json()
        assert len(nodes) >= 1

        # Find our node
        found = [n for n in nodes if n["public_ip"] == "5.6.7.8"]
        assert len(found) == 1
        assert found[0]["ip_type"] == "datacenter"
        assert found[0]["ip_region"] == "Ashburn, US"
