import logging

import httpx
from fastapi import FastAPI

from app.config import settings
from app.proxy import metrics

logger = logging.getLogger(__name__)

management_app = FastAPI(
    title="Space Router Proxy Gateway - Management",
    docs_url=None,
    redoc_url=None,
)


@management_app.get("/healthz")
async def healthz() -> dict:
    return {"status": "healthy"}


@management_app.get("/readyz")
async def readyz() -> dict:
    if not settings.COORDINATION_API_URL:
        return {"status": "not_ready", "reason": "coordination_api_url not configured"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.COORDINATION_API_URL}/healthz",
                timeout=3.0,
            )
            if resp.status_code == 200:
                return {"status": "ready"}
            return {"status": "not_ready", "reason": f"coordination API returned {resp.status_code}"}
    except httpx.HTTPError as e:
        return {"status": "not_ready", "reason": str(e)}


@management_app.get("/metrics")
async def get_metrics() -> dict:
    return {
        "total_requests": metrics["total_requests"],
        "active_connections": metrics["active_connections"],
        "successful_requests": metrics["successful_requests"],
        "auth_failures": metrics["auth_failures"],
        "rate_limited": metrics["rate_limited"],
        "upstream_errors": metrics["upstream_errors"],
        "no_nodes": metrics["no_nodes"],
        "socks5_total_requests": metrics["socks5_total_requests"],
        "socks5_active_connections": metrics["socks5_active_connections"],
        "socks5_auth_failures": metrics["socks5_auth_failures"],
        "socks5_successful_requests": metrics["socks5_successful_requests"],
    }
