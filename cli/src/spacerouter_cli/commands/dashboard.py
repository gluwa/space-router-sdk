"""``spacerouter dashboard`` — dashboard data access."""

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


@app.command("transfers")
@cli_error_handler
def transfers(
    wallet_address: Annotated[str, typer.Option("--wallet-address", help="Wallet address to query.")],
    page: Annotated[Optional[int], typer.Option("--page", help="Page number.")] = None,
    page_size: Annotated[Optional[int], typer.Option("--page-size", help="Results per page.")] = None,
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Get paginated data transfer history."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        result = admin.get_transfers(
            wallet_address=wallet_address,
            page=page,
            page_size=page_size,
        )
    print_json(result.model_dump())
