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


@app.command("list")
@cli_error_handler
def list_nodes(
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """List all registered nodes."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        nodes = admin.list_nodes()
    print_json([n.model_dump() for n in nodes])


@app.command("register")
@cli_error_handler
def register(
    endpoint_url: Annotated[str, typer.Option("--endpoint-url", help="Node endpoint URL.")],
    wallet_address: Annotated[str, typer.Option("--wallet-address", help="Node wallet address.")],
    label: Annotated[Optional[str], typer.Option("--label", help="Human-readable label.")] = None,
    connectivity_type: Annotated[
        Optional[str], typer.Option("--connectivity-type", help="direct, upnp, or external_provider.")
    ] = None,
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Register a new proxy node."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        node = admin.register_node(
            endpoint_url=endpoint_url,
            wallet_address=wallet_address,
            label=label,
            connectivity_type=connectivity_type,
        )
    print_json(node.model_dump())


@app.command("update-status")
@cli_error_handler
def update_status(
    node_id: Annotated[str, typer.Argument(help="Node ID.")],
    status: Annotated[str, typer.Option("--status", help="offline or draining. To go online, use request-probe.")],
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Update a node's operational status."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        admin.update_node_status(node_id, status=status)  # type: ignore[arg-type]
    print_json({"ok": True})


@app.command("request-probe")
@cli_error_handler
def request_probe(
    node_id: Annotated[str, typer.Argument(help="Node ID.")],
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Request a health probe for an offline node. If the probe passes, the node goes online."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        admin.request_probe(node_id)
    print_json({"ok": True, "message": "Probe queued. Node will go online if probe passes."})


@app.command("delete")
@cli_error_handler
def delete(
    node_id: Annotated[str, typer.Argument(help="Node ID.")],
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Delete a registered node."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        admin.delete_node(node_id)
    print_json({"ok": True})


@app.command("register-challenge")
@cli_error_handler
def register_challenge(
    address: Annotated[str, typer.Option("--address", help="Wallet address.")],
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Request a signing challenge for staking registration."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        challenge = admin.get_register_challenge(address)
    print_json(challenge.model_dump())


@app.command("register-verify")
@cli_error_handler
def register_verify(
    address: Annotated[str, typer.Option("--address", help="Wallet address.")],
    endpoint_url: Annotated[str, typer.Option("--endpoint-url", help="Node endpoint URL.")],
    signed_nonce: Annotated[str, typer.Option("--signed-nonce", help="Signed nonce from challenge.")],
    label: Annotated[Optional[str], typer.Option("--label", help="Human-readable label.")] = None,
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """Verify a signed nonce and register the node via staking."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    with SpaceRouterAdmin(cfg.coordination_api_url) as admin:
        result = admin.verify_and_register(
            address=address,
            endpoint_url=endpoint_url,
            signed_nonce=signed_nonce,
            label=label,
        )
    print_json(result.model_dump())
