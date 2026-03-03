"""Tests for the internal endpoints (proxy-gateway contract)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import SupabaseClient
from app.main import app
from app.services.auth_service import AuthService
from app.services.routing_service import RoutingService


def _setup_app(settings: Settings, mock_supabase) -> TestClient:
    """Wire up the app with test dependencies."""
    http_client = httpx.AsyncClient()
    db = SupabaseClient(http_client, settings)
    app.state.settings = settings
    app.state.http_client = http_client
    app.state.db = db
    app.state.auth_service = AuthService(db)
    app.state.routing_service = RoutingService(db, settings)
    return TestClient(app, raise_server_exceptions=False)


class TestAuthValidate:
    def test_valid_key(self, settings, mock_supabase):
        mock_supabase.get(f"{settings.SUPABASE_URL}/rest/v1/api_keys").respond(
            200,
            json={"id": "key-001", "rate_limit_rpm": 120},
            headers={"content-type": "application/json"},
        )
        client = _setup_app(settings, mock_supabase)
        resp = client.post(
            "/internal/auth/validate",
            json={"key_hash": "abc123hash"},
            headers={"Authorization": f"Bearer {settings.INTERNAL_API_SECRET}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["api_key_id"] == "key-001"
        assert data["rate_limit_rpm"] == 120

    def test_invalid_key(self, settings, mock_supabase):
        mock_supabase.get(f"{settings.SUPABASE_URL}/rest/v1/api_keys").respond(
            406,  # PostgREST returns 406 when single-object mode finds no rows
            headers={"content-type": "application/json"},
        )
        client = _setup_app(settings, mock_supabase)
        resp = client.post(
            "/internal/auth/validate",
            json={"key_hash": "nonexistent"},
            headers={"Authorization": f"Bearer {settings.INTERNAL_API_SECRET}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    def test_missing_auth_header(self, settings, mock_supabase):
        client = _setup_app(settings, mock_supabase)
        resp = client.post(
            "/internal/auth/validate",
            json={"key_hash": "abc123hash"},
        )
        assert resp.status_code == 422  # FastAPI requires the header

    def test_wrong_auth_secret(self, settings, mock_supabase):
        client = _setup_app(settings, mock_supabase)
        resp = client.post(
            "/internal/auth/validate",
            json={"key_hash": "abc123hash"},
            headers={"Authorization": "Bearer wrong-secret"},
        )
        assert resp.status_code == 401


class TestRouteSelect:
    def test_selects_from_db_nodes(self, settings, mock_supabase):
        mock_supabase.get(f"{settings.SUPABASE_URL}/rest/v1/nodes").respond(
            200,
            json=[
                {
                    "id": "node-abc",
                    "endpoint_url": "http://192.168.1.1:8443",
                    "health_score": 0.95,
                    "node_type": "residential",
                },
            ],
        )
        client = _setup_app(settings, mock_supabase)
        resp = client.get(
            "/internal/route/select",
            headers={"Authorization": f"Bearer {settings.INTERNAL_API_SECRET}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == "node-abc"
        assert data["endpoint_url"] == "http://192.168.1.1:8443"

    def test_falls_back_to_proxyjet(self, settings, mock_supabase):
        mock_supabase.get(f"{settings.SUPABASE_URL}/rest/v1/nodes").respond(200, json=[])
        client = _setup_app(settings, mock_supabase)
        resp = client.get(
            "/internal/route/select",
            headers={"Authorization": f"Bearer {settings.INTERNAL_API_SECRET}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == settings.PROXYJET_NODE_ID
        assert "proxy.proxyjet.io" in data["endpoint_url"]
        assert "user123" in data["endpoint_url"]
        assert "pass456" in data["endpoint_url"]

    def test_no_nodes_no_proxyjet(self, mock_supabase):
        # No proxyjet configured → 503
        no_proxyjet_settings = Settings(
            PORT=8000,
            INTERNAL_API_SECRET="test-secret",
            SUPABASE_URL="http://supabase.test",
            SUPABASE_SERVICE_KEY="test-service-key",
            PROXYJET_HOST="",  # Not configured
        )
        mock_supabase.get(f"{no_proxyjet_settings.SUPABASE_URL}/rest/v1/nodes").respond(200, json=[])
        client = _setup_app(no_proxyjet_settings, mock_supabase)
        resp = client.get(
            "/internal/route/select",
            headers={"Authorization": f"Bearer {no_proxyjet_settings.INTERNAL_API_SECRET}"},
        )
        assert resp.status_code == 503

    def test_db_error_falls_back_to_proxyjet(self, settings, mock_supabase):
        mock_supabase.get(f"{settings.SUPABASE_URL}/rest/v1/nodes").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        client = _setup_app(settings, mock_supabase)
        resp = client.get(
            "/internal/route/select",
            headers={"Authorization": f"Bearer {settings.INTERNAL_API_SECRET}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == settings.PROXYJET_NODE_ID


class TestRouteReport:
    def test_report_success(self, settings, mock_supabase):
        mock_supabase.post(f"{settings.SUPABASE_URL}/rest/v1/route_outcomes").respond(201)
        mock_supabase.get(f"{settings.SUPABASE_URL}/rest/v1/route_outcomes").respond(
            200,
            json=[{"success": True}, {"success": True}, {"success": False}],
        )
        mock_supabase.patch(f"{settings.SUPABASE_URL}/rest/v1/nodes").respond(204)

        client = _setup_app(settings, mock_supabase)
        resp = client.post(
            "/internal/route/report",
            json={
                "node_id": "node-abc",
                "success": True,
                "latency_ms": 150,
                "bytes": 4096,
            },
            headers={"Authorization": f"Bearer {settings.INTERNAL_API_SECRET}"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
