"""API key management endpoints.

These are user/admin-facing endpoints for creating and managing API keys.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Remove the prefix to fix the 404 issue
router = APIRouter(tags=["api-keys"])


def _generate_api_key() -> str:
    """Generate a new API key with sr_live_ prefix."""
    return f"sr_live_{secrets.token_hex(24)}"


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class CreateApiKeyRequest(BaseModel):
    name: str
    rate_limit_rpm: int = 60


class CreateApiKeyResponse(BaseModel):
    id: str
    name: str
    api_key: str  # Only returned at creation time
    rate_limit_rpm: int


@router.post("/api-keys", status_code=201)
async def create_api_key(body: CreateApiKeyRequest, request: Request) -> CreateApiKeyResponse:
    db = request.app.state.db
    client_ip = request.client.host if request.client else "unknown"

    # Rate limit: one API key per IP address per day
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    try:
        existing = await db.select(
            "api_keys",
            params={
                "created_by_ip": f"eq.{client_ip}",
                "created_at": f"gte.{today_start}",
            },
        )
        if existing:
            raise HTTPException(
                status_code=429,
                detail="Rate limited: only one API key may be issued per IP address per day",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to check IP rate limit: %s", e)
        raise HTTPException(status_code=500, detail="Failed to check IP rate limit")

    api_key = _generate_api_key()
    key_hash = _hash_key(api_key)

    try:
        rows = await db.insert(
            "api_keys",
            {
                "name": body.name,
                "key_hash": key_hash,
                "key_prefix": api_key[:12],
                "rate_limit_rpm": body.rate_limit_rpm,
                "is_active": True,
                "created_by_ip": client_ip,
            },
            return_rows=True,
        )
        if not rows:
            raise Exception("No rows returned after insert")

    except Exception as e:
        logger.exception("Failed to create API key: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create API key")

    row = rows[0]
    return CreateApiKeyResponse(
        id=row["id"],
        name=row["name"],
        api_key=api_key,
        rate_limit_rpm=row["rate_limit_rpm"],
    )


class ApiKeyInfo(BaseModel):
    id: str
    name: str
    key_prefix: str
    rate_limit_rpm: int
    is_active: bool
    created_at: str


@router.get("/api-keys")
async def list_api_keys(request: Request) -> list[ApiKeyInfo]:
    db = request.app.state.db
    try:
        rows = await db.select("api_keys")
        return [ApiKeyInfo(**r) for r in rows]
    except Exception as e:
        logger.exception("Failed to list API keys: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list API keys")


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: str, request: Request) -> None:
    db = request.app.state.db
    try:
        await db.update(
            "api_keys",
            {"is_active": False},
            params={"id": key_id},
        )
    except Exception as e:
        logger.exception("Failed to revoke API key %s: %s", key_id, e)
        raise HTTPException(status_code=500, detail="Failed to revoke API key")