"""Identity wallet management commands."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True)

_DEFAULT_KEYSTORE = str(Path.home() / ".spacerouter" / "identity.json")


def _ensure_wallet_dep() -> None:
    """Ensure eth-account is installed."""
    try:
        from spacerouter.identity import ClientIdentity  # noqa: F401
    except ImportError:
        typer.echo(
            json.dumps({"error": "Wallet features require eth-account. "
                        "Install with: pip install spacerouter[wallet]"}),
        )
        raise typer.Exit(1)


@app.command()
def generate(
    keystore_path: str = typer.Option(
        _DEFAULT_KEYSTORE,
        "--keystore-path", "-k",
        help="Path to save the identity keystore.",
    ),
    passphrase: bool = typer.Option(
        False,
        "--passphrase", "-p",
        help="Prompt for encryption passphrase.",
    ),
) -> None:
    """Generate a new identity wallet."""
    _ensure_wallet_dep()
    from spacerouter.identity import ClientIdentity

    pw = ""
    if passphrase:
        pw = typer.prompt("Enter passphrase", hide_input=True, confirmation_prompt=True)

    if os.path.isfile(keystore_path):
        typer.echo(json.dumps({"error": f"File already exists: {keystore_path}"}))
        raise typer.Exit(1)

    identity = ClientIdentity.generate(keystore_path=keystore_path, passphrase=pw)
    typer.echo(json.dumps({
        "status": "created",
        "address": identity.address,
        "keystore_path": keystore_path,
        "encrypted": bool(pw),
    }))


@app.command()
def show(
    keystore_path: str = typer.Option(
        _DEFAULT_KEYSTORE,
        "--keystore-path", "-k",
        help="Path to the identity keystore.",
    ),
    passphrase: str = typer.Option(
        "",
        "--passphrase", "-p",
        help="Passphrase for encrypted keystore (or empty for plaintext).",
    ),
) -> None:
    """Show the identity address from the configured keystore."""
    _ensure_wallet_dep()
    from spacerouter.identity import ClientIdentity

    if not os.path.isfile(keystore_path):
        typer.echo(json.dumps({"error": f"Keystore not found: {keystore_path}"}))
        raise typer.Exit(1)

    try:
        identity = ClientIdentity.from_keystore(keystore_path, passphrase)
    except ValueError as e:
        typer.echo(json.dumps({"error": str(e)}))
        raise typer.Exit(1)

    typer.echo(json.dumps({
        "address": identity.address,
        "keystore_path": keystore_path,
    }))


@app.command(name="export")
def export_keystore(
    keystore_path: str = typer.Option(
        _DEFAULT_KEYSTORE,
        "--keystore-path", "-k",
        help="Path to the source identity keystore.",
    ),
    output: str = typer.Option(
        ...,
        "--output", "-o",
        help="Output path for the exported keystore.",
    ),
    passphrase: str = typer.Option(
        "",
        "--passphrase", "-p",
        help="Passphrase for the source keystore.",
    ),
    encrypt: bool = typer.Option(
        True,
        "--encrypt/--no-encrypt",
        help="Encrypt the exported keystore.",
    ),
) -> None:
    """Export identity to a new encrypted keystore file."""
    _ensure_wallet_dep()
    from spacerouter.identity import ClientIdentity

    if not os.path.isfile(keystore_path):
        typer.echo(json.dumps({"error": f"Keystore not found: {keystore_path}"}))
        raise typer.Exit(1)

    try:
        identity = ClientIdentity.from_keystore(keystore_path, passphrase)
    except ValueError as e:
        typer.echo(json.dumps({"error": str(e)}))
        raise typer.Exit(1)

    export_pw = ""
    if encrypt:
        export_pw = typer.prompt(
            "Enter export passphrase", hide_input=True, confirmation_prompt=True,
        )

    identity.save_keystore(output, export_pw)
    typer.echo(json.dumps({
        "status": "exported",
        "address": identity.address,
        "output_path": output,
        "encrypted": bool(export_pw),
    }))
