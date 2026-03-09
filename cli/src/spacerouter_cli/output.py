"""Structured output for AI agent consumption.

All commands go through these functions so output format is consistent.
JSON by default; agents can parse stdout for data and stderr for errors.
"""

from __future__ import annotations

import functools
import json
import sys
from typing import Any

import httpx
import typer

from spacerouter.exceptions import (
    AuthenticationError,
    NoNodesAvailableError,
    RateLimitError,
    SpaceRouterError,
    UpstreamError,
)


def print_json(data: Any) -> None:
    """Print compact JSON to stdout."""
    typer.echo(json.dumps(data, indent=2, default=str))


def print_error(error_type: str, message: str, **extra: Any) -> None:
    """Print structured error JSON to stderr."""
    payload = {"error": error_type, "message": message, **extra}
    typer.echo(json.dumps(payload, indent=2, default=str), err=True)


def cli_error_handler(func):
    """Decorator that catches SDK/httpx errors and outputs structured JSON."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except AuthenticationError as e:
            print_error(
                "authentication_error",
                str(e),
                status_code=e.status_code,
                request_id=e.request_id,
            )
            raise typer.Exit(code=2)
        except RateLimitError as e:
            print_error(
                "rate_limit_error",
                str(e),
                retry_after=e.retry_after,
                status_code=e.status_code,
                request_id=e.request_id,
            )
            raise typer.Exit(code=3)
        except NoNodesAvailableError as e:
            print_error(
                "no_nodes_available",
                str(e),
                status_code=e.status_code,
                request_id=e.request_id,
            )
            raise typer.Exit(code=4)
        except UpstreamError as e:
            print_error(
                "upstream_error",
                str(e),
                node_id=e.node_id,
                status_code=e.status_code,
                request_id=e.request_id,
            )
            raise typer.Exit(code=5)
        except httpx.HTTPStatusError as e:
            print_error(
                "http_error",
                str(e),
                status_code=e.response.status_code,
            )
            raise typer.Exit(code=5)
        except httpx.HTTPError as e:
            print_error("connection_error", str(e))
            raise typer.Exit(code=5)
        except SpaceRouterError as e:
            print_error(
                "spacerouter_error",
                str(e),
                status_code=e.status_code,
                request_id=e.request_id,
            )
            raise typer.Exit(code=10)
        except typer.Exit:
            raise
        except Exception as e:
            print_error("unexpected_error", str(e))
            raise typer.Exit(code=10)

    return wrapper
