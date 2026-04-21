"""``spacerouter receipts`` — on-chain receipt state queries.

Consumer-facing view. Given a client address + request UUID, check
whether the escrow has settled that receipt on-chain. JSON output
only.

For a provider's *local* receipt state (signed vs failed vs locked),
see the provider CLI at ``python -m app.main --receipts`` on the
node — that operates against the provider's local SQLite, not the
chain.
"""

from __future__ import annotations

import os
from typing import Annotated, Optional

import typer

from spacerouter_cli.commands.escrow import (
    ContractOpt, RpcOpt, _resolve_client,
)
from spacerouter_cli.output import cli_error_handler, print_json

app = typer.Typer(
    help=(
        "Query on-chain Leg 2 receipt state. For provider-local "
        "receipt state, run `python -m app.main --receipts` on the node."
    ),
    no_args_is_help=True,
)


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
