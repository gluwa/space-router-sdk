"""``spacerouter node`` — view node information."""

from __future__ import annotations

from typing import Annotated, Optional

import httpx
import typer

from spacerouter_cli.config import resolve_config
from spacerouter_cli.output import cli_error_handler, print_json

app = typer.Typer(no_args_is_help=True)

CoordinationUrlOpt = Annotated[
    Optional[str],
    typer.Option("--coordination-url", help="Coordination API URL."),
]


@app.command("list")
@cli_error_handler
def list_nodes(
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """List all registered nodes."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    response = httpx.get(f"{cfg.coordination_api_url}/nodes", timeout=10.0)
    response.raise_for_status()
    print_json(response.json())
