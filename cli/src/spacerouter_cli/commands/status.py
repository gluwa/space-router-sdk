"""``spacerouter status`` — check service health."""

from __future__ import annotations

from typing import Annotated, Optional

import httpx
import typer

from spacerouter_cli.config import resolve_config
from spacerouter_cli.output import cli_error_handler, print_json

CoordinationUrlOpt = Annotated[
    Optional[str],
    typer.Option("--coordination-url", help="Coordination API URL."),
]
GatewayMgmtOpt = Annotated[
    Optional[str],
    typer.Option("--gateway-management-url", help="Gateway management API URL."),
]


@cli_error_handler
def status(
    coordination_url: CoordinationUrlOpt = None,
    gateway_management_url: GatewayMgmtOpt = None,
) -> None:
    """Check Coordination API and Proxy Gateway health."""
    cfg = resolve_config(
        coordination_api_url=coordination_url,
        gateway_management_url=gateway_management_url,
    )
    results: dict = {}

    # Coordination API
    try:
        resp = httpx.get(f"{cfg.coordination_api_url}/healthz", timeout=5.0)
        results["coordination_api"] = {
            "url": cfg.coordination_api_url,
            "status": "healthy" if resp.status_code == 200 else "unhealthy",
            "status_code": resp.status_code,
        }
    except httpx.HTTPError as e:
        results["coordination_api"] = {
            "url": cfg.coordination_api_url,
            "status": "unreachable",
            "error": str(e),
        }

    # Proxy Gateway management
    try:
        health = httpx.get(f"{cfg.gateway_management_url}/healthz", timeout=5.0)
        ready = httpx.get(f"{cfg.gateway_management_url}/readyz", timeout=5.0)
        results["gateway"] = {
            "url": cfg.gateway_management_url,
            "healthy": health.status_code == 200,
            "ready": ready.json().get("status") == "ready",
        }
    except httpx.HTTPError as e:
        results["gateway"] = {
            "url": cfg.gateway_management_url,
            "status": "unreachable",
            "error": str(e),
        }

    coord_ok = results.get("coordination_api", {}).get("status") == "healthy"
    gw_ok = results.get("gateway", {}).get("healthy", False)
    results["overall"] = "healthy" if (coord_ok and gw_ok) else "degraded"

    print_json(results)
    raise typer.Exit(code=0 if results["overall"] == "healthy" else 1)
