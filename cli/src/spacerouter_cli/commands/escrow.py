"""``spacerouter escrow`` — TokenPaymentEscrow wallet operations.

Consumer-facing view of on-chain balance and withdrawal state. JSON
output only (agent-friendly). Read operations work without a private
key; deposits / withdrawals require one via ``--private-key`` or
``SR_ESCROW_PRIVATE_KEY``.

This command group operates against the on-chain contract directly.
For a provider's *local* receipt state (signed/failed/retryable),
see the provider CLI at
``python -m app.main --receipts`` on the node.
"""

from __future__ import annotations

import os
from typing import Annotated, Optional

import typer

from spacerouter.escrow import EscrowClient
from spacerouter_cli.output import cli_error_handler, print_json

app = typer.Typer(
    help="Query and interact with the TokenPaymentEscrow contract on-chain.",
    no_args_is_help=True,
)


ENV_RPC = "SR_ESCROW_CHAIN_RPC"
ENV_CONTRACT = "SR_ESCROW_CONTRACT_ADDRESS"
ENV_PRIVATE_KEY = "SR_ESCROW_PRIVATE_KEY"


RpcOpt = Annotated[
    Optional[str],
    typer.Option(
        "--rpc-url",
        help=(
            "Creditcoin RPC endpoint. Env: SR_ESCROW_CHAIN_RPC. "
            "Default test: https://rpc.cc3-testnet.creditcoin.network"
        ),
    ),
]
ContractOpt = Annotated[
    Optional[str],
    typer.Option(
        "--contract-address",
        help="TokenPaymentEscrow proxy address. Env: SR_ESCROW_CONTRACT_ADDRESS.",
    ),
]
PrivateKeyOpt = Annotated[
    Optional[str],
    typer.Option(
        "--private-key",
        help=(
            "Wallet private key for write operations. "
            "Env: SR_ESCROW_PRIVATE_KEY. Never log or commit."
        ),
    ),
]


def _resolve_client(
    rpc_url: Optional[str],
    contract_address: Optional[str],
    private_key: Optional[str] = None,
) -> EscrowClient:
    rpc = rpc_url or os.environ.get(ENV_RPC)
    contract = contract_address or os.environ.get(ENV_CONTRACT)
    key = private_key or os.environ.get(ENV_PRIVATE_KEY)

    if not rpc:
        raise typer.BadParameter(
            "Missing RPC URL. Use --rpc-url or set SR_ESCROW_CHAIN_RPC.",
        )
    if not contract:
        raise typer.BadParameter(
            "Missing contract address. Use --contract-address or set "
            "SR_ESCROW_CONTRACT_ADDRESS.",
        )
    return EscrowClient(
        rpc_url=rpc, contract_address=contract, private_key=key,
    )


@app.command("balance")
@cli_error_handler
def balance(
    address: Annotated[
        str, typer.Argument(help="Address to query escrow balance for."),
    ],
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
) -> None:
    """Escrow balance for an address, in wei (18-decimal SPACE)."""
    client = _resolve_client(rpc_url, contract_address)
    wei = client.balance(address)
    print_json({
        "address": address,
        "escrow_balance_wei": wei,
        "escrow_balance_space": wei / 10**18,
    })


@app.command("token-balance")
@cli_error_handler
def token_balance(
    address: Annotated[
        str, typer.Argument(help="Address to query undeposited token balance for."),
    ],
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
) -> None:
    """Undeposited (wallet-held) SPACE token balance in wei."""
    client = _resolve_client(rpc_url, contract_address)
    wei = client.token_balance(address)
    print_json({
        "address": address,
        "token_balance_wei": wei,
        "token_balance_space": wei / 10**18,
    })


@app.command("withdrawal-request")
@cli_error_handler
def withdrawal_request(
    address: Annotated[
        str, typer.Argument(help="Address whose pending withdrawal to inspect."),
    ],
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
) -> None:
    """Pending withdrawal state: amount + unlock timestamp."""
    client = _resolve_client(rpc_url, contract_address)
    amount, unlock_at, exists = client.withdrawal_request(address)
    print_json({
        "address": address,
        "has_pending_withdrawal": exists,
        "amount_wei": amount,
        "amount_space": amount / 10**18,
        "unlock_at_epoch_seconds": unlock_at,
    })


@app.command("withdrawal-delay")
@cli_error_handler
def withdrawal_delay(
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
) -> None:
    """Contract-wide withdrawal delay in seconds."""
    client = _resolve_client(rpc_url, contract_address)
    delay = client.withdrawal_delay()
    print_json({
        "withdrawal_delay_seconds": delay,
        "withdrawal_delay_days": delay / 86400,
    })


@app.command("deposit")
@cli_error_handler
def deposit(
    amount_wei: Annotated[
        int,
        typer.Argument(help="Amount to deposit, in wei (18-decimal)."),
    ],
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
    private_key: PrivateKeyOpt = None,
) -> None:
    """Deposit tokens into the escrow. Requires a private key."""
    client = _resolve_client(rpc_url, contract_address, private_key)
    tx_hash = client.deposit(int(amount_wei))
    print_json({
        "action": "deposit",
        "amount_wei": int(amount_wei),
        "tx_hash": tx_hash,
        "from": client.address,
    })


@app.command("initiate-withdrawal")
@cli_error_handler
def initiate_withdrawal(
    amount_wei: Annotated[
        int,
        typer.Argument(help="Amount to withdraw, in wei."),
    ],
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
    private_key: PrivateKeyOpt = None,
) -> None:
    """Start a withdrawal. Subject to the contract's withdrawal delay."""
    client = _resolve_client(rpc_url, contract_address, private_key)
    tx_hash = client.initiate_withdrawal(int(amount_wei))
    print_json({
        "action": "initiate_withdrawal",
        "amount_wei": int(amount_wei),
        "tx_hash": tx_hash,
        "from": client.address,
    })


@app.command("execute-withdrawal")
@cli_error_handler
def execute_withdrawal(
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
    private_key: PrivateKeyOpt = None,
) -> None:
    """Finalise a previously-initiated withdrawal after the delay has elapsed."""
    client = _resolve_client(rpc_url, contract_address, private_key)
    tx_hash = client.execute_withdrawal()
    print_json({
        "action": "execute_withdrawal",
        "tx_hash": tx_hash,
        "from": client.address,
    })


@app.command("cancel-withdrawal")
@cli_error_handler
def cancel_withdrawal(
    rpc_url: RpcOpt = None,
    contract_address: ContractOpt = None,
    private_key: PrivateKeyOpt = None,
) -> None:
    """Cancel a pending withdrawal request before it unlocks."""
    client = _resolve_client(rpc_url, contract_address, private_key)
    tx_hash = client.cancel_withdrawal()
    print_json({
        "action": "cancel_withdrawal",
        "tx_hash": tx_hash,
        "from": client.address,
    })
