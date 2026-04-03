"""``spacerouter regions`` — discover available proxy regions."""
from __future__ import annotations

from typing import Annotated, Optional

import httpx
import typer

from spacerouter_cli.config import resolve_config
from spacerouter_cli.output import cli_error_handler, print_json

CoordinationUrlOpt = Annotated[
    Optional[str],
    typer.Option("--coordination-url", help="Coordination API URL."),
]
IpTypeOpt = Annotated[
    Optional[str],
    typer.Option("--ip-type", help="Filter to regions with this IP type."),
]


@cli_error_handler
def regions(
    ip_type: IpTypeOpt = None,
    coordination_url: CoordinationUrlOpt = None,
) -> None:
    """List available proxy regions and IP types."""
    cfg = resolve_config(coordination_api_url=coordination_url)
    params: dict[str, str] = {}
    if ip_type:
        params["ip_type"] = ip_type
    response = httpx.get(
        f"{cfg.coordination_api_url}/regions",
        params=params,
        timeout=10.0,
    )
    if response.status_code >= 400:
        from spacerouter_cli.output import print_error

        print_error("regions_error", f"Failed ({response.status_code}): {response.text}")
        raise typer.Exit(code=5)
    print_json(response.json())
