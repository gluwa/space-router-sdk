"""``spacerouter request`` — make proxied HTTP requests."""

from __future__ import annotations

import json as _json
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
) -> None:
    cfg = resolve_config(api_key=api_key, gateway_url=gateway_url, timeout=timeout)

    if not cfg.api_key:
        print_error("configuration_error", "API key is required. Set SR_API_KEY or pass --api-key.")
        raise typer.Exit(code=1)

    headers = _parse_headers(header)
    kwargs: dict = {"headers": headers}
    if data is not None:
        try:
            kwargs["json"] = _json.loads(data)
        except (ValueError, TypeError):
            print_error("configuration_error", "Invalid JSON in --data flag.")
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
) -> None:
    """Send a GET request through the residential proxy."""
    _do_request("GET", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects)


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
) -> None:
    """Send a POST request through the residential proxy."""
    _do_request("POST", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects, data=data)


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
) -> None:
    """Send a PUT request through the residential proxy."""
    _do_request("PUT", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects, data=data)


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
) -> None:
    """Send a PATCH request through the residential proxy."""
    _do_request("PATCH", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects, data=data)


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
) -> None:
    """Send a DELETE request through the residential proxy."""
    _do_request("DELETE", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects)


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
) -> None:
    """Send a HEAD request through the residential proxy."""
    _do_request("HEAD", url, api_key=api_key, gateway_url=gateway_url, header=header,
                region=region, ip_type=ip_type, timeout=timeout,
                output=output, follow_redirects=follow_redirects)
