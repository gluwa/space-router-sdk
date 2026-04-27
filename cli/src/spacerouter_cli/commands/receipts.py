"""``spacerouter receipts`` — on-chain receipt state queries + Leg 1 settlement.

Two flavours of "receipt" surfaced here:

* On-chain queries (``is-settled``, ``show``) hit the
  ``TokenPaymentEscrow`` contract directly and report whether a given
  ``(client, request_uuid)`` pair has been claimed.
* Leg 1 settlement queries (``pending``, ``sync``, ``list``) hit the
  Gateway management API at ``/leg1/...``. These are the unsigned
  receipts the Gateway is holding for the consumer to sign and submit
  back via EIP-712.

For a provider's *local* receipt state (signed vs failed vs locked),
see the provider CLI at ``python -m app.main --receipts`` on the
node — that operates against the provider's local SQLite, not the
chain or the Gateway broker.
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import time
from typing import Annotated, Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from spacerouter.payment.consumer_settlement import ConsumerSettlementClient

from spacerouter_cli.commands.escrow import (
    ContractOpt, RpcOpt, _resolve_client,
)
from spacerouter_cli.config import (
    ENV_GATEWAY_MANAGEMENT_URL, DEFAULT_GATEWAY_MANAGEMENT_URL,
)
from spacerouter_cli.output import cli_error_handler, print_error, print_json

app = typer.Typer(
    help=(
        "Query Leg 1 broker pending receipts, sync EIP-712 signatures, "
        "and inspect on-chain Leg 2 receipt state."
    ),
    no_args_is_help=True,
)


ENV_PRIVATE_KEY = "SR_ESCROW_PRIVATE_KEY"


GatewayMgmtOpt = Annotated[
    Optional[str],
    typer.Option(
        "--gateway",
        help=(
            "Gateway management URL. "
            "Env: SR_GATEWAY_MANAGEMENT_URL."
        ),
    ),
]
PrivateKeyOpt = Annotated[
    Optional[str],
    typer.Option(
        "--key",
        help=(
            "Consumer wallet private key (signs EIP-191 auth + EIP-712 "
            "receipts). Env: SR_ESCROW_PRIVATE_KEY. Never log or commit."
        ),
    ),
]
LimitOpt = Annotated[
    int,
    typer.Option(
        "--limit",
        help="Max receipts to fetch per call (default 50, broker max 200).",
    ),
]
JsonOpt = Annotated[
    bool,
    typer.Option(
        "--json",
        help="Emit structured JSON to stdout instead of a Rich table.",
    ),
]
WatchOpt = Annotated[
    Optional[float],
    typer.Option(
        "--watch",
        help=(
            "If set, repeat sync every N seconds until interrupted. "
            "CTRL-C exits cleanly with a cumulative summary."
        ),
    ),
]
ClientFilterOpt = Annotated[
    Optional[str],
    typer.Option(
        "--client",
        help=(
            "Filter the listing to a specific client_address. "
            "Display-side only — the broker still returns receipts owned "
            "by --key."
        ),
    ),
]


def _resolve_settlement(
    gateway_url: Optional[str],
    private_key: Optional[str],
) -> ConsumerSettlementClient:
    gw = gateway_url or os.environ.get(ENV_GATEWAY_MANAGEMENT_URL) \
        or DEFAULT_GATEWAY_MANAGEMENT_URL
    key = private_key or os.environ.get(ENV_PRIVATE_KEY)
    if not key:
        raise typer.BadParameter(
            "Missing private key. Pass --key or set SR_ESCROW_PRIVATE_KEY.",
        )
    return ConsumerSettlementClient(gateway_url=gw, private_key=key)


def _normalise_receipts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Coerce wire values: ``data_amount``/``total_price`` always int."""
    rows = []
    for r in payload.get("receipts", []):
        rows.append({
            "request_uuid": r.get("request_uuid"),
            "tunnel_request_id": r.get("tunnel_request_id"),
            "client_address": r.get("client_address"),
            "node_address": r.get("node_address"),
            "data_amount": int(r.get("data_amount", 0)),
            "total_price": int(r.get("total_price", 0)),
            "created_at": r.get("created_at"),
        })
    return rows


def _render_pending_table(
    receipts: list[dict[str, Any]], domain: dict[str, Any] | None,
) -> None:
    console = Console()
    if not receipts:
        console.print("[dim]No pending Leg 1 receipts.[/dim]")
        return
    table = Table(
        title=f"Pending Leg 1 receipts ({len(receipts)})",
        title_style="bold",
        show_lines=False,
    )
    table.add_column("request_uuid", overflow="fold")
    table.add_column("tunnel", overflow="fold")
    table.add_column("data (B)", justify="right")
    table.add_column("price (wei)", justify="right")
    table.add_column("created_at", overflow="fold")
    for r in receipts:
        table.add_row(
            str(r.get("request_uuid", "")),
            str(r.get("tunnel_request_id", "")),
            f"{int(r.get('data_amount', 0)):,}",
            f"{int(r.get('total_price', 0)):,}",
            str(r.get("created_at", "")),
        )
    console.print(table)
    if domain:
        console.print(
            f"[dim]EIP-712 domain: {domain.get('name')} v{domain.get('version')} "
            f"chainId={domain.get('chainId')} contract={domain.get('verifyingContract')}[/dim]",
        )


def _render_sync_table(result: dict[str, Any]) -> None:
    console = Console()
    accepted = result.get("accepted", []) or []
    rejected = result.get("rejected", []) or []
    pending = result.get("pending_count", len(accepted) + len(rejected))
    table = Table(title="Leg 1 sync result", title_style="bold")
    table.add_column("metric")
    table.add_column("count", justify="right")
    table.add_row("pending fetched", str(pending))
    table.add_row("[green]accepted[/green]", str(len(accepted)))
    table.add_row("[red]rejected[/red]", str(len(rejected)))
    console.print(table)
    if rejected:
        rej_table = Table(
            title="Rejected reasons", title_style="bold red", show_lines=False,
        )
        rej_table.add_column("request_uuid", overflow="fold")
        rej_table.add_column("reason", overflow="fold")
        for r in rejected:
            rej_table.add_row(
                str(r.get("request_uuid", "")),
                str(r.get("reason", "")),
            )
        console.print(rej_table)


# ── new Leg 1 broker commands ───────────────────────────────────────


@app.command("pending")
@cli_error_handler
def pending(
    limit: LimitOpt = 50,
    gateway: GatewayMgmtOpt = None,
    key: PrivateKeyOpt = None,
    json_output: JsonOpt = False,
) -> None:
    """List unsigned Leg 1 receipts the Gateway is holding for this consumer."""
    settler = _resolve_settlement(gateway, key)
    payload = asyncio.run(settler.fetch_pending(limit=limit))
    receipts = _normalise_receipts(payload)
    if json_output:
        print_json({
            "address": settler.address,
            "pending_count": len(receipts),
            "receipts": receipts,
            "domain": payload.get("domain"),
        })
        return
    _render_pending_table(receipts, payload.get("domain"))


@app.command("list")
@cli_error_handler
def list_cmd(
    limit: LimitOpt = 50,
    client: ClientFilterOpt = None,
    json_output: JsonOpt = False,
    gateway: GatewayMgmtOpt = None,
    key: PrivateKeyOpt = None,
) -> None:
    """List pending Leg 1 receipts grouped by ``tunnel_request_id``."""
    settler = _resolve_settlement(gateway, key)
    payload = asyncio.run(settler.fetch_pending(limit=limit))
    receipts = _normalise_receipts(payload)

    if client:
        wanted = client.lower()
        receipts = [
            r for r in receipts
            if str(r.get("client_address", "")).lower() == wanted
        ]

    # Group by tunnel_request_id (None grouped under "<no-tunnel>").
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in receipts:
        tun = r.get("tunnel_request_id") or "<no-tunnel>"
        groups.setdefault(tun, []).append(r)

    if json_output:
        print_json({
            "address": settler.address,
            "filter_client": client,
            "pending_count": len(receipts),
            "groups": [
                {"tunnel_request_id": tun, "receipts": items}
                for tun, items in groups.items()
            ],
        })
        return

    console = Console()
    if not receipts:
        console.print("[dim]No pending Leg 1 receipts.[/dim]")
        return
    for tun, items in groups.items():
        table = Table(
            title=f"Tunnel {tun} ({len(items)} receipt(s))",
            title_style="bold",
            show_lines=False,
        )
        table.add_column("request_uuid", overflow="fold")
        table.add_column("client_address", overflow="fold")
        table.add_column("data (B)", justify="right")
        table.add_column("price (wei)", justify="right")
        table.add_column("created_at", overflow="fold")
        for r in items:
            table.add_row(
                str(r.get("request_uuid", "")),
                str(r.get("client_address", "")),
                f"{int(r.get('data_amount', 0)):,}",
                f"{int(r.get('total_price', 0)):,}",
                str(r.get("created_at", "")),
            )
        console.print(table)


@app.command("sync")
@cli_error_handler
def sync(
    limit: LimitOpt = 50,
    gateway: GatewayMgmtOpt = None,
    key: PrivateKeyOpt = None,
    json_output: JsonOpt = False,
    watch: WatchOpt = None,
) -> None:
    """Sign every pending Leg 1 receipt and submit signatures to the broker."""
    settler = _resolve_settlement(gateway, key)

    if watch is None:
        result = asyncio.run(settler.sync_receipts(limit=limit))
        if json_output:
            print_json(result)
        else:
            _render_sync_table(result)
        return

    # ---- watch loop ------------------------------------------------------
    if watch <= 0:
        raise typer.BadParameter("--watch must be a positive number of seconds.")
    console = Console()
    cumulative_accepted: list[str] = []
    cumulative_rejected: list[dict[str, Any]] = []
    iterations = 0
    try:
        while True:
            iterations += 1
            try:
                result = asyncio.run(settler.sync_receipts(limit=limit))
            except Exception as exc:  # noqa: BLE001 — bounded recovery
                console.print(
                    f"[yellow]iter {iterations} failed: {exc}; will retry[/yellow]",
                )
                # Sleep but still respect KeyboardInterrupt promptly.
                time.sleep(watch)
                continue
            cumulative_accepted.extend(result.get("accepted", []) or [])
            cumulative_rejected.extend(result.get("rejected", []) or [])
            if json_output:
                # one JSON object per iteration so log scrapers can stream.
                typer.echo(_json.dumps({
                    "iteration": iterations,
                    "result": result,
                }, default=str))
            else:
                console.print(
                    f"[dim]iter {iterations}:[/dim] "
                    f"accepted={len(result.get('accepted', []) or [])} "
                    f"rejected={len(result.get('rejected', []) or [])} "
                    f"pending={result.get('pending_count', 0)}",
                )
            time.sleep(watch)
    except KeyboardInterrupt:
        pass

    summary = {
        "iterations": iterations,
        "accepted_total": len(cumulative_accepted),
        "rejected_total": len(cumulative_rejected),
        "rejected": cumulative_rejected,
    }
    if json_output:
        print_json({"watch_summary": summary})
    else:
        console.print(
            f"\n[bold]watch summary:[/bold] iterations={iterations} "
            f"accepted_total={summary['accepted_total']} "
            f"rejected_total={summary['rejected_total']}",
        )
        if cumulative_rejected:
            rej_table = Table(
                title="Rejected reasons (cumulative)",
                title_style="bold red",
            )
            rej_table.add_column("request_uuid", overflow="fold")
            rej_table.add_column("reason", overflow="fold")
            for r in cumulative_rejected:
                rej_table.add_row(
                    str(r.get("request_uuid", "")),
                    str(r.get("reason", "")),
                )
            console.print(rej_table)


# ── existing on-chain queries (do not modify behaviour) ─────────────


@app.command("is-settled")
@cli_error_handler
def is_settled(
    client_address: Annotated[
        str, typer.Argument(help="Receipt client (payer) address."),
    ],
    request_uuid: Annotated[
        str, typer.Argument(help="Receipt UUID (per-client nonce)."),
    ],
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
) -> None:
    """Check whether a specific receipt has been claimed on-chain."""
    client = _resolve_client(rpc_url, contract_address)
    used = client.is_nonce_used(client_address, request_uuid)
    print_json({
        "client_address": client_address,
        "request_uuid": request_uuid,
        "settled_on_chain": used,
    })


@app.command("show")
@cli_error_handler
def show(
    client_address: Annotated[
        str, typer.Argument(help="Receipt client (payer) address."),
    ],
    request_uuid: Annotated[
        str, typer.Argument(help="Receipt UUID."),
    ],
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
) -> None:
    """Alias for ``is-settled`` — returns the same on-chain state."""
    client = _resolve_client(rpc_url, contract_address)
    used = client.is_nonce_used(client_address, request_uuid)
    print_json({
        "client_address": client_address,
        "request_uuid": request_uuid,
        "settled_on_chain": used,
        "status": "claimed" if used else "unclaimed_on_chain",
    })
