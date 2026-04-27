"""``spacerouter request`` — make proxied HTTP requests.

Two payment modes:

* **API key** (legacy / default) — pass ``--api-key`` or set ``SR_API_KEY``.
* **Escrow / SPACE** — pass ``--pay`` together with a wallet private key
  via ``--key`` or ``SR_ESCROW_PRIVATE_KEY``. Adding ``--auto-settle``
  also runs ``payment.sync_receipts()`` after the request so any Leg 1
  receipt the gateway parked is signed and submitted in one step.

The two modes are mutually exclusive at the call site; backward compat
is preserved when neither ``--pay`` nor ``--auto-settle`` is set.
"""

from __future__ import annotations

import asyncio
import json as _json
import os
from typing import Annotated, Optional

import typer

from spacerouter import SpaceRouter

from spacerouter_cli.config import resolve_config
from spacerouter_cli.output import cli_error_handler, print_error, print_json

app = typer.Typer(no_args_is_help=True)

# -- shared option types -----------------------------------------------------

ApiKeyOpt = Annotated[Optional[str], typer.Option("--api-key", help="API key for proxy auth.")]
GatewayOpt = Annotated[Optional[str], typer.Option("--gateway-url", help="Proxy gateway URL.")]
HeaderOpt = Annotated[Optional[list[str]], typer.Option("--header", "-H", help="Custom header (Name: Value). Repeatable.")]
RegionOpt = Annotated[Optional[str], typer.Option("--region", help="2-letter country code (e.g. US, KR).")]
IpTypeOpt = Annotated[Optional[str], typer.Option("--ip-type", help="IP type filter: residential, mobile, datacenter, business.")]
TimeoutOpt = Annotated[Optional[float], typer.Option("--timeout", help="Request timeout in seconds.")]
OutputOpt = Annotated[str, typer.Option("--output", help="Output mode: json (structured) or raw (body only).")]
FollowOpt = Annotated[bool, typer.Option("--follow-redirects", help="Follow HTTP redirects.")]
DataOpt = Annotated[Optional[str], typer.Option("--data", "-d", help="JSON request body.")]

# -- escrow payment mode -----------------------------------------------------

PayOpt = Annotated[
    bool,
    typer.Option(
        "--pay",
        help=(
            "Use SPACE/escrow payment instead of API key. Requires --key "
            "or SR_ESCROW_PRIVATE_KEY."
        ),
    ),
]
AutoSettleOpt = Annotated[
    bool,
    typer.Option(
        "--auto-settle",
        help=(
            "After --pay, run payment.sync_receipts() to sign and submit "
            "any pending Leg 1 receipts. No-op without --pay."
        ),
    ),
]
PayKeyOpt = Annotated[
    Optional[str],
    typer.Option(
        "--key",
        help=(
            "Consumer wallet private key for --pay / --auto-settle. "
            "Env: SR_ESCROW_PRIVATE_KEY."
        ),
    ),
]
EscrowContractOpt = Annotated[
    Optional[str],
    typer.Option(
        "--escrow-contract",
        help=(
            "TokenPaymentEscrow proxy address used to scope EIP-712 "
            "signatures. Env: SR_ESCROW_CONTRACT_ADDRESS."
        ),
    ),
]
ChainIdOpt = Annotated[
    Optional[int],
    typer.Option(
        "--chain-id",
        help="Chain ID for EIP-712 domain. Env: SR_ESCROW_CHAIN_ID. Default 102031.",
    ),
]


ENV_PAY_KEY = "SR_ESCROW_PRIVATE_KEY"
ENV_ESCROW_CONTRACT = "SR_ESCROW_CONTRACT_ADDRESS"
ENV_CHAIN_ID = "SR_ESCROW_CHAIN_ID"


def _parse_headers(raw: list[str] | None) -> dict[str, str]:
    """Parse ``["Name: Value", ...]`` into a dict."""
    if not raw:
        return {}
    headers: dict[str, str] = {}
    for item in raw:
        name, _, value = item.partition(":")
        headers[name.strip()] = value.strip()
    return headers


def _try_parse_json(text: str):
    """Attempt to parse *text* as JSON; return raw string on failure."""
    try:
        return _json.loads(text)
    except (ValueError, TypeError):
        return text


def _do_request(
    method: str,
    url: str,
    *,
    api_key: str | None,
    gateway_url: str | None,
    header: list[str] | None,
    region: str | None,
    ip_type: str | None = None,
    timeout: float | None,
    output: str,
    follow_redirects: bool,
    data: str | None = None,
    pay: bool = False,
    auto_settle: bool = False,
    pay_key: str | None = None,
    escrow_contract: str | None = None,
    chain_id: int | None = None,
) -> None:
    cfg = resolve_config(api_key=api_key, gateway_url=gateway_url, timeout=timeout)

    headers = _parse_headers(header)
    kwargs: dict = {"headers": headers}
    if data is not None:
        try:
            kwargs["json"] = _json.loads(data)
        except (ValueError, TypeError):
            print_error("configuration_error", "Invalid JSON in --data flag.")
            raise typer.Exit(code=1)

    # ---- Escrow / SPACE payment mode --------------------------------
    if pay:
        _do_paid_request(
            method, url,
            kwargs=kwargs,
            cfg=cfg,
            region=region,
            ip_type=ip_type,
            follow_redirects=follow_redirects,
            output=output,
            auto_settle=auto_settle,
            pay_key=pay_key,
            escrow_contract=escrow_contract,
            chain_id=chain_id,
        )
        return

    if auto_settle:
        print_error(
            "configuration_error",
            "--auto-settle requires --pay (escrow mode). Add --pay or drop --auto-settle.",
        )
        raise typer.Exit(code=1)

    if not cfg.api_key:
        print_error("configuration_error", "API key is required. Set SR_API_KEY or pass --api-key.")
        raise typer.Exit(code=1)

    with SpaceRouter(
        cfg.api_key,
        gateway_url=cfg.gateway_url,
        region=region,
        ip_type=ip_type,
        timeout=cfg.timeout,
        follow_redirects=follow_redirects,
    ) as client:
        resp = client.request(method, url, **kwargs)

    if output == "raw":
        typer.echo(resp.text)
    else:
        print_json({
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "body": _try_parse_json(resp.text),
            "spacerouter": {
                "request_id": resp.request_id,
            },
        })


def _do_paid_request(
    method: str,
    url: str,
    *,
    kwargs: dict,
    cfg,
    region: str | None,
    ip_type: str | None,
    follow_redirects: bool,
    output: str,
    auto_settle: bool,
    pay_key: str | None,
    escrow_contract: str | None,
    chain_id: int | None,
) -> None:
    """Escrow / SPACE-paid request path.

    Builds a :class:`SpaceRouterSPACE` consumer client, fetches a fresh
    challenge, signs it, attaches the four ``X-SpaceRouter-*`` headers
    to the proxied request, and (if ``--auto-settle``) runs
    ``sync_receipts()`` afterwards.

    The actual proxy request reuses :class:`SpaceRouter` for transport
    so we don't reimplement httpx CONNECT plumbing — the SDK is paid by
    presenting headers instead of a Proxy-Authorization API key.
    """
    from spacerouter.payment import SpaceRouterSPACE

    key = pay_key or os.environ.get(ENV_PAY_KEY)
    if not key:
        print_error(
            "configuration_error",
            "--pay requires a wallet private key. Pass --key or set SR_ESCROW_PRIVATE_KEY.",
        )
        raise typer.Exit(code=1)

    contract = escrow_contract or os.environ.get(ENV_ESCROW_CONTRACT) or ""
    cid_raw = chain_id if chain_id is not None else os.environ.get(ENV_CHAIN_ID)
    cid = int(cid_raw) if cid_raw is not None else 102031

    # Gateway management URL is used by SpaceRouterSPACE for /auth/challenge
    # and by ConsumerSettlementClient for /leg1/...; the proxy URL is the
    # CONNECT endpoint and is what SpaceRouter() takes as gateway_url.
    consumer = SpaceRouterSPACE(
        gateway_url=cfg.gateway_management_url,
        proxy_url=cfg.gateway_url,
        private_key=key,
        chain_id=cid,
        escrow_contract=contract,
    )

    # Delegate payment-header injection to SpaceRouter(payment=...) — it
    # places the headers on the proxy CONNECT (where the gateway can
    # read them) rather than on the inner TLS-tunneled request (which
    # the gateway can't see). Setting `auto_settle` here also runs
    # `sync_receipts()` after a successful response.
    settle_summary: dict | None = None
    paid_principal = consumer.address.lower()

    with SpaceRouter(
        paid_principal,
        gateway_url=cfg.gateway_url,
        region=region,
        ip_type=ip_type,
        timeout=cfg.timeout,
        follow_redirects=follow_redirects,
        payment=consumer,
        auto_settle=False,  # we run sync_receipts() ourselves to surface the summary
    ) as client:
        resp = client.request(method, url, **kwargs)

    if auto_settle:
        try:
            settle_summary = asyncio.run(consumer.sync_receipts())
        except Exception as exc:  # noqa: BLE001 — surface, never poison the request
            settle_summary = {"error": str(exc)}

    if output == "raw":
        typer.echo(resp.text)
        if settle_summary is not None:
            typer.echo(_json.dumps(
                {"auto_settle": settle_summary}, default=str,
            ), err=True)
        return

    payload = {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "body": _try_parse_json(resp.text),
        "spacerouter": {
            "request_id": resp.request_id,
            "payer_address": consumer.address,
            "payment_mode": "escrow",
        },
    }
    if settle_summary is not None:
        payload["auto_settle"] = settle_summary
    print_json(payload)


# -- subcommands --------------------------------------------------------------


@app.command()
@cli_error_handler
def get(
    url: str,
    api_key: ApiKeyOpt = None,
    gateway_url: GatewayOpt = None,
    header: HeaderOpt = None,
    region: RegionOpt = None,
    ip_type: IpTypeOpt = None,
    timeout: TimeoutOpt = None,
    output: OutputOpt = "json",
    follow_redirects: FollowOpt = False,
    pay: PayOpt = False,
    auto_settle: AutoSettleOpt = False,
    pay_key: PayKeyOpt = None,
    escrow_contract: EscrowContractOpt = None,
    chain_id: ChainIdOpt = None,
) -> None:
    """Send a GET request through the residential proxy."""
    _do_request("GET", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects,
                pay=pay, auto_settle=auto_settle, pay_key=pay_key,
                escrow_contract=escrow_contract, chain_id=chain_id)


@app.command()
@cli_error_handler
def post(
    url: str,
    api_key: ApiKeyOpt = None,
    gateway_url: GatewayOpt = None,
    header: HeaderOpt = None,
    data: DataOpt = None,
    region: RegionOpt = None,
    ip_type: IpTypeOpt = None,
    timeout: TimeoutOpt = None,
    output: OutputOpt = "json",
    follow_redirects: FollowOpt = False,
    pay: PayOpt = False,
    auto_settle: AutoSettleOpt = False,
    pay_key: PayKeyOpt = None,
    escrow_contract: EscrowContractOpt = None,
    chain_id: ChainIdOpt = None,
) -> None:
    """Send a POST request through the residential proxy."""
    _do_request("POST", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects, data=data,
                pay=pay, auto_settle=auto_settle, pay_key=pay_key,
                escrow_contract=escrow_contract, chain_id=chain_id)


@app.command()
@cli_error_handler
def put(
    url: str,
    api_key: ApiKeyOpt = None,
    gateway_url: GatewayOpt = None,
    header: HeaderOpt = None,
    data: DataOpt = None,
    region: RegionOpt = None,
    ip_type: IpTypeOpt = None,
    timeout: TimeoutOpt = None,
    output: OutputOpt = "json",
    follow_redirects: FollowOpt = False,
    pay: PayOpt = False,
    auto_settle: AutoSettleOpt = False,
    pay_key: PayKeyOpt = None,
    escrow_contract: EscrowContractOpt = None,
    chain_id: ChainIdOpt = None,
) -> None:
    """Send a PUT request through the residential proxy."""
    _do_request("PUT", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects, data=data,
                pay=pay, auto_settle=auto_settle, pay_key=pay_key,
                escrow_contract=escrow_contract, chain_id=chain_id)


@app.command()
@cli_error_handler
def patch(
    url: str,
    api_key: ApiKeyOpt = None,
    gateway_url: GatewayOpt = None,
    header: HeaderOpt = None,
    data: DataOpt = None,
    region: RegionOpt = None,
    ip_type: IpTypeOpt = None,
    timeout: TimeoutOpt = None,
    output: OutputOpt = "json",
    follow_redirects: FollowOpt = False,
    pay: PayOpt = False,
    auto_settle: AutoSettleOpt = False,
    pay_key: PayKeyOpt = None,
    escrow_contract: EscrowContractOpt = None,
    chain_id: ChainIdOpt = None,
) -> None:
    """Send a PATCH request through the residential proxy."""
    _do_request("PATCH", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects, data=data,
                pay=pay, auto_settle=auto_settle, pay_key=pay_key,
                escrow_contract=escrow_contract, chain_id=chain_id)


@app.command()
@cli_error_handler
def delete(
    url: str,
    api_key: ApiKeyOpt = None,
    gateway_url: GatewayOpt = None,
    header: HeaderOpt = None,
    region: RegionOpt = None,
    ip_type: IpTypeOpt = None,
    timeout: TimeoutOpt = None,
    output: OutputOpt = "json",
    follow_redirects: FollowOpt = False,
    pay: PayOpt = False,
    auto_settle: AutoSettleOpt = False,
    pay_key: PayKeyOpt = None,
    escrow_contract: EscrowContractOpt = None,
    chain_id: ChainIdOpt = None,
) -> None:
    """Send a DELETE request through the residential proxy."""
    _do_request("DELETE", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects,
                pay=pay, auto_settle=auto_settle, pay_key=pay_key,
                escrow_contract=escrow_contract, chain_id=chain_id)


@app.command()
@cli_error_handler
def head(
    url: str,
    api_key: ApiKeyOpt = None,
    gateway_url: GatewayOpt = None,
    header: HeaderOpt = None,
    region: RegionOpt = None,
    ip_type: IpTypeOpt = None,
    timeout: TimeoutOpt = None,
    output: OutputOpt = "json",
    follow_redirects: FollowOpt = False,
    pay: PayOpt = False,
    auto_settle: AutoSettleOpt = False,
    pay_key: PayKeyOpt = None,
    escrow_contract: EscrowContractOpt = None,
    chain_id: ChainIdOpt = None,
) -> None:
    """Send a HEAD request through the residential proxy."""
    _do_request("HEAD", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects,
                pay=pay, auto_settle=auto_settle, pay_key=pay_key,
                escrow_contract=escrow_contract, chain_id=chain_id)
