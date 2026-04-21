"""SpaceRouter CLI — AI-agent-friendly tool for residential proxy requests."""

from __future__ import annotations

import json

import typer

from spacerouter_cli import __version__
from spacerouter_cli.commands import (
    api_key, billing, config_cmd, dashboard, escrow, node, receipts,
    request, status,
)

app = typer.Typer(
    name="spacerouter",
    help="CLI for the Space Router residential proxy network. Designed for AI agents.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

app.add_typer(request.app, name="request", help="Make proxied HTTP requests")
app.add_typer(api_key.app, name="api-key", help="Manage API keys")
app.add_typer(node.app, name="node", help="Manage proxy nodes")
app.add_typer(billing.app, name="billing", help="Billing and checkout")
app.add_typer(dashboard.app, name="dashboard", help="Dashboard data")
app.add_typer(config_cmd.app, name="config", help="Configuration management")
app.add_typer(escrow.app, name="escrow", help="Escrow wallet / deposit / withdrawal")
app.add_typer(receipts.app, name="receipts", help="On-chain Leg 2 receipt state queries")
app.command(name="status", help="Check service health")(status.status)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(json.dumps({"version": __version__}))
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Show CLI version and exit.",
    ),
) -> None:
    """SpaceRouter CLI — residential proxy requests for AI agents."""
