"""Shared test fixtures for the SpaceRouter Python SDK."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_ca_cert_fetch():
    """Prevent tests from making real HTTP calls to fetch the CA cert.

    All client tests run with ``fetch_ca_cert`` returning ``None`` so the
    client falls back to the default system CAs (``verify=True``).

    Yields the *patcher* so individual tests can ``.stop()`` / ``.start()``
    it when they need to exercise the real ``fetch_ca_cert`` implementation.
    """
    patcher = patch("spacerouter.client.fetch_ca_cert", return_value=None)
    patcher.start()
    yield patcher
    try:
        patcher.stop()
    except RuntimeError:
        pass  # already stopped by a test that called .stop()
