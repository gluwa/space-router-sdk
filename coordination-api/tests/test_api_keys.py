"""Tests for the API key management endpoints."""

import asyncio

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.services.auth_service import AuthService
from app.services.routing_service import RoutingService
from app.sqlite_db import SQLiteClient


def _setup_app(settings: Settings) -> TestClient:
    http_client = httpx.AsyncClient()
    db = SQLiteClient(settings.SQLITE_DB_PATH)
    app.state.settings = settings
    app.state.http_client = http_client
    app.state.db = db
    app.state.auth_service = AuthService(http_client, settings)
    app.state.routing_service = RoutingService(http_client, settings)
    return TestClient(app, raise_server_exceptions=False)


class TestCreateApiKey:
    def test_create_success(self, settings):
        client = _setup_app(settings)
        resp = client.post(
            "/api-keys",
            json={"name": "My Agent Key"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Agent Key"
        assert data["api_key"].startswith("sr_live_")
        assert len(data["api_key"]) == 56  # "sr_live_" (8) + 48 hex chars
        assert data["rate_limit_rpm"] == 60

    def test_create_with_custom_rpm(self, settings):
        client = _setup_app(settings)
        resp = client.post(
            "/api-keys",
            json={"name": "High RPM Key", "rate_limit_rpm": 200},
        )
        assert resp.status_code == 201
        assert resp.json()["rate_limit_rpm"] == 200


class TestListApiKeys:
    def test_list_keys(self, settings):
        client = _setup_app(settings)
        # Insert keys directly to avoid IP rate limit (both from same test client IP)
        db = app.state.db
        asyncio.run(db.insert("api_keys", {
            "name": "Key 1", "key_hash": "hash1", "key_prefix": "sr_live_aaa1",
            "rate_limit_rpm": 60, "is_active": True, "created_by_ip": "1.1.1.1",
        }))
        asyncio.run(db.insert("api_keys", {
            "name": "Key 2", "key_hash": "hash2", "key_prefix": "sr_live_aaa2",
            "rate_limit_rpm": 60, "is_active": True, "created_by_ip": "2.2.2.2",
        }))
        resp = client.get("/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Raw api_key never returned in list
        assert "api_key" not in data[0]


class TestIpRateLimit:
    def test_second_key_same_ip_same_day_rejected(self, settings):
        client = _setup_app(settings)
        # First key creation should succeed
        resp1 = client.post("/api-keys", json={"name": "First Key"})
        assert resp1.status_code == 201

        # Second key from the same IP on the same day should be rejected
        resp2 = client.post("/api-keys", json={"name": "Second Key"})
        assert resp2.status_code == 429
        assert "one API key" in resp2.json()["detail"]

    def test_first_key_stores_ip(self, settings):
        client = _setup_app(settings)
        resp = client.post("/api-keys", json={"name": "IP Key"})
        assert resp.status_code == 201

        # Verify the IP was stored in the database
        db = app.state.db
        rows = asyncio.run(
            db.select("api_keys", params={"id": resp.json()["id"]})
        )
        assert rows[0]["created_by_ip"] is not None


class TestRevokeApiKey:
    def test_revoke(self, settings):
        client = _setup_app(settings)
        # Create a key first
        create_resp = client.post("/api-keys", json={"name": "Temp Key"})
        key_id = create_resp.json()["id"]
        # Revoke it
        resp = client.delete(f"/api-keys/{key_id}")
        assert resp.status_code == 204
