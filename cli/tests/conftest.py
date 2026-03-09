"""Shared fixtures for CLI tests."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from spacerouter_cli.main import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def cli_env(monkeypatch):
    """Set standard env vars for testing."""
    monkeypatch.setenv("SR_API_KEY", "sr_live_test_key_000")
    monkeypatch.setenv("SR_GATEWAY_URL", "http://localhost:8080")
    monkeypatch.setenv("SR_COORDINATION_API_URL", "http://localhost:8000")
    monkeypatch.setenv("SR_GATEWAY_MANAGEMENT_URL", "http://localhost:8081")


def parse_json_output(output: str) -> dict | list:
    """Parse the first JSON object/array from CLI output.

    Some commands emit both stdout JSON and stderr JSON into the combined
    ``result.output``.  This helper finds the first valid JSON blob.
    """
    return json.loads(output)


def parse_last_json(output: str) -> dict | list:
    """Parse the *last* JSON object from CLI output.

    Useful when a command prints an error JSON after some other output.
    """
    # Walk backwards through lines to find the start of JSON
    lines = output.strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        candidate = "\n".join(lines[i:])
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    raise ValueError(f"No JSON found in output: {output!r}")
