"""``spacerouter config`` — configuration management."""

from __future__ import annotations

from typing import Annotated

import typer

from spacerouter_cli.config import (
    ALLOWED_CONFIG_KEYS,
    CONFIG_FILE,
    mask_key,
    resolve_config,
    save_config,
)
from spacerouter_cli.output import print_error, print_json

app = typer.Typer(no_args_is_help=True)


@app.command()
def show() -> None:
    """Display the resolved configuration (API key is masked)."""
    cfg = resolve_config()
    print_json({
        "api_key": mask_key(cfg.api_key),
        "gateway_url": cfg.gateway_url,
        "coordination_api_url": cfg.coordination_api_url,
        "gateway_management_url": cfg.gateway_management_url,
        "timeout": cfg.timeout,
        "config_file": str(CONFIG_FILE),
        "config_file_exists": CONFIG_FILE.exists(),
    })


@app.command("set")
def set_value(
    key: Annotated[str, typer.Argument(help=f"Config key. Allowed: {', '.join(sorted(ALLOWED_CONFIG_KEYS))}.")],
    value: Annotated[str, typer.Argument(help="Value to set.")],
) -> None:
    """Set a configuration value in ~/.spacerouter/config.json."""
    if key not in ALLOWED_CONFIG_KEYS:
        print_error(
            "invalid_config_key",
            f"Unknown key: {key}",
            allowed_keys=sorted(ALLOWED_CONFIG_KEYS),
        )
        raise typer.Exit(code=1)

    save_config({key: value})
    display_value = mask_key(value) if "key" in key else value
    print_json({"ok": True, "key": key, "value": display_value})
