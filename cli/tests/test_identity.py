"""Tests for ``spacerouter identity`` commands."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import parse_json_output, parse_last_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_KEY = "0x" + "ab" * 32
_TEST_ADDRESS = "0xa5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4"  # placeholder
_PASSPHRASE = "test-passphrase-42"

# A mock ClientIdentity that all commands will receive via the patched import.
def _make_mock_identity(address: str = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef") -> MagicMock:
    mock = MagicMock()
    mock.address = address
    return mock


# ---------------------------------------------------------------------------
# identity generate
# ---------------------------------------------------------------------------

class TestIdentityGenerate:
    @patch("spacerouter.identity.ClientIdentity")
    def test_generate_creates_wallet(self, mock_cls, runner, cli_env, tmp_path):
        """``identity generate`` creates a wallet and prints JSON with address."""
        keystore = str(tmp_path / "identity.json")
        mock_identity = _make_mock_identity()
        mock_cls.generate.return_value = mock_identity

        result = runner.invoke(
            _app(),
            ["identity", "generate", "--keystore-path", keystore],
        )

        assert result.exit_code == 0, result.output
        data = parse_json_output(result.output)
        assert data["status"] == "created"
        assert data["address"] == mock_identity.address
        assert data["keystore_path"] == keystore
        assert data["encrypted"] is False

    @patch("spacerouter.identity.ClientIdentity")
    def test_generate_fails_if_file_exists(self, mock_cls, runner, cli_env, tmp_path):
        """``identity generate`` exits with error when keystore already exists."""
        keystore = str(tmp_path / "identity.json")
        # Pre-create the file
        with open(keystore, "w") as f:
            f.write("{}")

        result = runner.invoke(
            _app(),
            ["identity", "generate", "--keystore-path", keystore],
        )

        assert result.exit_code != 0
        data = parse_json_output(result.output)
        assert "error" in data
        assert "already exists" in data["error"]

    @patch("spacerouter.identity.ClientIdentity")
    def test_generate_with_passphrase(self, mock_cls, runner, cli_env, tmp_path):
        """``identity generate --passphrase`` prompts for passphrase and marks encrypted=True."""
        keystore = str(tmp_path / "identity.json")
        mock_identity = _make_mock_identity()
        mock_cls.generate.return_value = mock_identity

        result = runner.invoke(
            _app(),
            ["identity", "generate", "--keystore-path", keystore, "--passphrase"],
            input=f"{_PASSPHRASE}\n{_PASSPHRASE}\n",
        )

        assert result.exit_code == 0, result.output
        data = parse_last_json(result.output)
        assert data["encrypted"] is True
        assert data["address"] == mock_identity.address


# ---------------------------------------------------------------------------
# identity show
# ---------------------------------------------------------------------------

class TestIdentityShow:
    @patch("spacerouter.identity.ClientIdentity")
    def test_show_existing_keystore(self, mock_cls, runner, cli_env, tmp_path):
        """``identity show`` prints address for a valid keystore."""
        keystore = str(tmp_path / "identity.json")
        # Create a dummy file so the existence check passes
        with open(keystore, "w") as f:
            f.write("{}")

        mock_identity = _make_mock_identity()
        mock_cls.from_keystore.return_value = mock_identity

        result = runner.invoke(
            _app(),
            ["identity", "show", "--keystore-path", keystore],
        )

        assert result.exit_code == 0, result.output
        data = parse_json_output(result.output)
        assert data["address"] == mock_identity.address
        assert data["keystore_path"] == keystore

    @patch("spacerouter.identity.ClientIdentity")
    def test_show_missing_keystore(self, mock_cls, runner, cli_env, tmp_path):
        """``identity show`` exits with error when keystore file is missing."""
        keystore = str(tmp_path / "nonexistent.json")

        result = runner.invoke(
            _app(),
            ["identity", "show", "--keystore-path", keystore],
        )

        assert result.exit_code != 0
        data = parse_json_output(result.output)
        assert "error" in data
        assert "not found" in data["error"]

    @patch("spacerouter.identity.ClientIdentity")
    def test_show_bad_passphrase(self, mock_cls, runner, cli_env, tmp_path):
        """``identity show`` exits with error on ValueError (wrong passphrase)."""
        keystore = str(tmp_path / "identity.json")
        with open(keystore, "w") as f:
            f.write("{}")

        mock_cls.from_keystore.side_effect = ValueError("passphrase required or incorrect")

        result = runner.invoke(
            _app(),
            ["identity", "show", "--keystore-path", keystore, "--passphrase"],
            input="wrong\n",
        )

        assert result.exit_code != 0
        data = parse_last_json(result.output)
        assert "error" in data


# ---------------------------------------------------------------------------
# identity export
# ---------------------------------------------------------------------------

class TestIdentityExport:
    @patch("spacerouter.identity.ClientIdentity")
    def test_export_no_encrypt(self, mock_cls, runner, cli_env, tmp_path):
        """``identity export --no-encrypt`` writes unencrypted keystore."""
        src = str(tmp_path / "src.json")
        dst = str(tmp_path / "exported.json")
        with open(src, "w") as f:
            f.write("{}")

        mock_identity = _make_mock_identity()
        mock_cls.from_keystore.return_value = mock_identity

        result = runner.invoke(
            _app(),
            [
                "identity", "export",
                "--keystore-path", src,
                "--output", dst,
                "--no-encrypt",
            ],
        )

        assert result.exit_code == 0, result.output
        data = parse_json_output(result.output)
        assert data["status"] == "exported"
        assert data["address"] == mock_identity.address
        assert data["output_path"] == dst
        assert data["encrypted"] is False
        mock_identity.save_keystore.assert_called_once_with(dst, "")

    @patch("spacerouter.identity.ClientIdentity")
    def test_export_with_encrypt(self, mock_cls, runner, cli_env, tmp_path):
        """``identity export --encrypt`` prompts for passphrase and marks encrypted=True."""
        src = str(tmp_path / "src.json")
        dst = str(tmp_path / "exported_enc.json")
        with open(src, "w") as f:
            f.write("{}")

        mock_identity = _make_mock_identity()
        mock_cls.from_keystore.return_value = mock_identity

        result = runner.invoke(
            _app(),
            [
                "identity", "export",
                "--keystore-path", src,
                "--output", dst,
                "--encrypt",
            ],
            input=f"{_PASSPHRASE}\n{_PASSPHRASE}\n",
        )

        assert result.exit_code == 0, result.output
        data = parse_last_json(result.output)
        assert data["status"] == "exported"
        assert data["encrypted"] is True
        mock_identity.save_keystore.assert_called_once_with(dst, _PASSPHRASE)

    @patch("spacerouter.identity.ClientIdentity")
    def test_export_missing_source(self, mock_cls, runner, cli_env, tmp_path):
        """``identity export`` exits with error when source keystore is missing."""
        src = str(tmp_path / "ghost.json")
        dst = str(tmp_path / "out.json")

        result = runner.invoke(
            _app(),
            [
                "identity", "export",
                "--keystore-path", src,
                "--output", dst,
                "--no-encrypt",
            ],
        )

        assert result.exit_code != 0
        data = parse_json_output(result.output)
        assert "error" in data
        assert "not found" in data["error"]

    @patch("spacerouter.identity.ClientIdentity")
    def test_export_bad_passphrase_on_source(self, mock_cls, runner, cli_env, tmp_path):
        """``identity export`` exits with error when source passphrase is wrong."""
        src = str(tmp_path / "enc.json")
        dst = str(tmp_path / "out.json")
        with open(src, "w") as f:
            f.write("{}")

        mock_cls.from_keystore.side_effect = ValueError("passphrase required or incorrect")

        result = runner.invoke(
            _app(),
            [
                "identity", "export",
                "--keystore-path", src,
                "--output", dst,
                "--passphrase",
                "--no-encrypt",
            ],
            input="wrong\n",
        )

        assert result.exit_code != 0
        data = parse_last_json(result.output)
        assert "error" in data


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _app():
    """Return the CLI app (deferred import to keep top-level imports clean)."""
    from spacerouter_cli.main import app
    return app
