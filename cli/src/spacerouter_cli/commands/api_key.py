"""``spacerouter api-key`` — manage API keys."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from spacerouter import SpaceRouterAdmin

from spacerouter_cli.config import resolve_config
from spacerouter_cli.output import cli_error_handler, print_json

app = typer.Typer(no_args_is_help=True)

CoordinationUrlOpt = Annotated[
    Optional[str],
    typer.Option("--coordination-url", help="Coordination API URL."),
]


@app.command()
@cli_error_handler
def create(
    name: Annotated[str, typer.Option("--name", help="Human-readable key name.")],
    rate_limit: Annotated[int, typer.Option("--rate-limit", help="Requests per minute.")] = 60,
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Create a new API key."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        key = admin.create_api_key(name, rate_limit_rpm=rate_limit)
    print_json({
        "id": key.id,
        "name": key.name,
        "api_key": key.api_key,
        "rate_limit_rpm": key.rate_limit_rpm,
    })


@app.command("list")
@cli_error_handler
def list_keys(
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """List all API keys."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        keys = admin.list_api_keys()
    print_json([k.model_dump() for k in keys])


@app.command()
@cli_error_handler
def revoke(
    key_id: Annotated[str, typer.Argument(help="ID of the API key to revoke.")],
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Revoke (soft-delete) an API key."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        admin.revoke_api_key(key_id)
    print_json({"ok": True, "revoked_key_id": key_id})
