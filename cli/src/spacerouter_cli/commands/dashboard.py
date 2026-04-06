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
    identity_address: Annotated[Optional[str], typer.Option("--identity-address", help="Identity address to query.")] = None,
    wallet_address: Annotated[Optional[str], typer.Option("--wallet-address", help="[Deprecated] Use --identity-address.", hidden=True)] = None,
    page: Annotated[Optional[int], typer.Option("--page", help="Page number.")] = None,
    page_size: Annotated[Optional[int], typer.Option("--page-size", help="Results per page.")] = None,
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Get paginated data transfer history."""
    addr = identity_address or wallet_address
    if not addr:
        raise typer.BadParameter("--identity-address is required")
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        result = admin.get_transfers(
            identity_address=addr,
            page=page,
            page_size=page_size,
        )
    print_json(result.model_dump())


@app.command("credit-line")
@cli_error_handler
def credit_line(
    address: Annotated[str, typer.Option("--address", help="Wallet address to check credit line for.")],
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Query credit line status for an address."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        result = admin.get_credit_line(address)
    print_json(result.model_dump())
