"""``spacerouter billing`` — billing and checkout management."""

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


@app.command("checkout")
@cli_error_handler
def checkout(
    email: Annotated[str, typer.Option("--email", help="Email for the checkout session.")],
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Create a Stripe checkout session."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        session = admin.create_checkout(email)
    print_json(session.model_dump())


@app.command("verify")
@cli_error_handler
def verify(
    token: Annotated[str, typer.Option("--token", help="Email verification token.")],
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Verify an email address."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        admin.verify_email(token)
    print_json({"ok": True})


@app.command("reissue")
@cli_error_handler
def reissue(
    email: Annotated[str, typer.Option("--email", help="Account email.")],
    token: Annotated[str, typer.Option("--token", help="Verification token.")],
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Reissue an API key using email verification."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        result = admin.reissue_api_key(email=email, token=token)
    print_json(result.model_dump())
