"""``spacerouter node`` — manage proxy nodes."""

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

IdentityKeyOpt = Annotated[
    Optional[str],
    typer.Option("--identity-key", help="Path to node identity key file. Default: ~/.spacerouter/identity.key"),
]


def _load_identity(key_path: str | None = None) -> str:
    """Load the node identity private key (auto-create if missing)."""
    from spacerouter.identity import load_or_create_identity, DEFAULT_IDENTITY_PATH
    path = key_path or DEFAULT_IDENTITY_PATH
    private_key, address = load_or_create_identity(path)
    return private_key


@app.command("list")
@cli_error_handler
def list_nodes(
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """List all registered nodes (deprecated — use 'get' instead)."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        nodes = admin.list_nodes()
    print_json([n.model_dump() for n in nodes])


@app.command("update-status")
@cli_error_handler
def update_status(
    node_id: Annotated[str, typer.Argument(help="Node ID.")],
    status: Annotated[str, typer.Option("--status", help="offline or draining. To go online, use request-probe.")],
    identity_key: IdentityKeyOpt = None,
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Update a node's operational status. Requires node identity key."""
    private_key = _load_identity(identity_key)
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        admin.update_node_status(node_id, status=status, private_key=private_key)  # type: ignore[arg-type]
    print_json({"ok": True})


@app.command("request-probe")
@cli_error_handler
def request_probe(
    node_id: Annotated[str, typer.Argument(help="Node ID.")],
    identity_key: IdentityKeyOpt = None,
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Request a health probe for an offline node. Requires node identity key."""
    private_key = _load_identity(identity_key)
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        admin.request_probe(node_id, private_key=private_key)
    print_json({"ok": True, "message": "Probe queued. Node will go online if probe passes."})


@app.command("delete")
@cli_error_handler
def delete(
    node_id: Annotated[str, typer.Argument(help="Node ID.")],
    identity_key: IdentityKeyOpt = None,
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Delete a registered node. Requires node identity key."""
    private_key = _load_identity(identity_key)
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        admin.delete_node(node_id, private_key=private_key)
    print_json({"ok": True})
