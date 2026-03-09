"""Configuration resolution for the SpaceRouter CLI.

Priority (highest to lowest):
  1. CLI flags (--api-key, --gateway-url, etc.)
  2. Environment variables (SR_API_KEY, SR_GATEWAY_URL, SR_COORDINATION_API_URL)
  3. Config file (~/.spacerouter/config.json)
  4. Built-in defaults
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".spacerouter"
CONFIG_FILE = CONFIG_DIR / "config.json"

ENV_API_KEY = "SR_API_KEY"
ENV_GATEWAY_URL = "SR_GATEWAY_URL"
ENV_COORDINATION_API_URL = "SR_COORDINATION_API_URL"
ENV_GATEWAY_MANAGEMENT_URL = "SR_GATEWAY_MANAGEMENT_URL"

DEFAULT_GATEWAY_URL = "http://localhost:8080"
DEFAULT_COORDINATION_API_URL = "http://localhost:8000"
DEFAULT_GATEWAY_MANAGEMENT_URL = "http://localhost:8081"
DEFAULT_TIMEOUT = 30.0

ALLOWED_CONFIG_KEYS = {
    "api_key",
    "gateway_url",
    "coordination_api_url",
    "gateway_management_url",
    "timeout",
}


@dataclass
class CLIConfig:
    api_key: str | None = None
    gateway_url: str = DEFAULT_GATEWAY_URL
    coordination_api_url: str = DEFAULT_COORDINATION_API_URL
    gateway_management_url: str = DEFAULT_GATEWAY_MANAGEMENT_URL
    timeout: float = DEFAULT_TIMEOUT


def load_config_file() -> dict:
    """Load config file, returning empty dict if missing or invalid."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def resolve_config(**cli_overrides: str | float | None) -> CLIConfig:
    """Merge config file -> env vars -> CLI overrides.

    Values that are ``None`` in a higher-priority layer are skipped so
    lower-priority values can fill in.
    """
    file_cfg = load_config_file()

    def _pick(key: str, env_var: str | None = None, default: str | float | None = None):
        # CLI flag first
        cli_val = cli_overrides.get(key)
        if cli_val is not None:
            return cli_val
        # Env var second
        if env_var:
            env_val = os.environ.get(env_var)
            if env_val is not None:
                return env_val
        # Config file third
        file_val = file_cfg.get(key)
        if file_val is not None:
            return file_val
        # Default last
        return default

    return CLIConfig(
        api_key=_pick("api_key", ENV_API_KEY),
        gateway_url=_pick("gateway_url", ENV_GATEWAY_URL, DEFAULT_GATEWAY_URL),
        coordination_api_url=_pick(
            "coordination_api_url", ENV_COORDINATION_API_URL, DEFAULT_COORDINATION_API_URL
        ),
        gateway_management_url=_pick(
            "gateway_management_url", ENV_GATEWAY_MANAGEMENT_URL, DEFAULT_GATEWAY_MANAGEMENT_URL
        ),
        timeout=float(_pick("timeout", None, DEFAULT_TIMEOUT)),
    )


def save_config(updates: dict) -> None:
    """Write *updates* into ~/.spacerouter/config.json (merge, not overwrite)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_config_file()
    existing.update(updates)
    CONFIG_FILE.write_text(json.dumps(existing, indent=2) + "\n")


def mask_key(value: str | None) -> str | None:
    """Mask an API key for display: ``sr_live_abc1****``."""
    if not value:
        return value
    if len(value) <= 12:
        return value[:4] + "****"
    return value[:12] + "****"
