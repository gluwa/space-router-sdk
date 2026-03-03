"""Tests for the API key management endpoints."""

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import SupabaseClient
from app.main import app
from app.services.auth_service import AuthService
from app.services.routing_service import RoutingService


def _setup_app(settings: Settings, mock_supabase) -> TestClient:
    http_client = httpx.AsyncClient()
    db = SupabaseClient(http_client, settings)
    app.state.settings = settings
    app.state.http_client = http_client
    app.state.db = db
    app.state.auth_service = AuthService(db)
    app.state.routing_service = RoutingService(db, settings)
    return TestClient(app, raise_server_exceptions=False)


class TestCreateApiKey:
    def test_create_success(self, settings, mock_supabase):
        mock_supabase.post(f"{settings.SUPABASE_URL}/rest/v1/api_keys").respond(
            201,
            json=[{
                "id": "key-001",
                "name": "My Agent Key",
                "key_hash": "somehash",
                "key_prefix": "sr_live_abcd",
                "rate_limit_rpm": 60,
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
            }],
        )
        client = _setup_app(settings, mock_supabase)
        resp = client.post(
            "/api-keys",
            json={"name": "My Agent Key"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "key-001"
        assert data["name"] == "My Agent Key"
        assert data["api_key"].startswith("sr_live_")
        assert len(data["api_key"]) == 56  # "sr_live_" (8) + 48 hex chars

    def test_create_with_custom_rpm(self, settings, mock_supabase):
        mock_supabase.post(f"{settings.SUPABASE_URL}/rest/v1/api_keys").respond(
            201,
            json=[{
                "id": "key-002",
                "name": "High RPM Key",
                "key_hash": "somehash",
                "key_prefix": "sr_live_efgh",
                "rate_limit_rpm": 200,
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
            }],
        )
        client = _setup_app(settings, mock_supabase)
        resp = client.post(
            "/api-keys",
            json={"name": "High RPM Key", "rate_limit_rpm": 200},
        )
        assert resp.status_code == 201
        assert resp.json()["rate_limit_rpm"] == 200


class TestListApiKeys:
    def test_list_keys(self, settings, mock_supabase):
        mock_supabase.get(f"{settings.SUPABASE_URL}/rest/v1/api_keys").respond(
            200,
            json=[
                {
                    "id": "key-001",
                    "name": "Key 1",
                    "key_prefix": "sr_live_aaaa",
                    "rate_limit_rpm": 60,
                    "is_active": True,
                    "created_at": "2024-01-01T00:00:00Z",
                },
                {
                    "id": "key-002",
                    "name": "Key 2",
                    "key_prefix": "sr_live_bbbb",
                    "rate_limit_rpm": 120,
                    "is_active": False,
                    "created_at": "2024-01-02T00:00:00Z",
                },
            ],
        )
        client = _setup_app(settings, mock_supabase)
        resp = client.get("/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Keys never returned in list
        assert "api_key" not in data[0]


class TestRevokeApiKey:
    def test_revoke(self, settings, mock_supabase):
        mock_supabase.patch(f"{settings.SUPABASE_URL}/rest/v1/api_keys").respond(204)
        client = _setup_app(settings, mock_supabase)
        resp = client.delete("/api-keys/key-001")
        assert resp.status_code == 204
