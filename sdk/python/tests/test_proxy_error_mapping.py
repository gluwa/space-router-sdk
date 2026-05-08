"""rc.10 #1 + #2: CONNECT-time 407/503 typed-error mapping + async cleanup.

The rc.6 (407) and rc.8 (503) Response-path mappings in
``client._check_proxy_errors`` only fire when httpx returns a Response.
CONNECT-tunnel failures raise ``httpx.ProxyError`` BEFORE any Response
exists, so those mappings never matched in production for bad API keys
or no-nodes-available — the SDK leaked a raw ``httpx.ProxyError`` to
consumers. Same architectural class of bug the JS SDK shipped through
rc.6→rc.8 (J-06 5-cycle).

Tests use a real local CONNECT-returning HTTP server, NOT mocked
exceptions. The JS SDK shipped J-06 across five release cycles because
hand-built mocks misrepresented the real exception shape — undici
inserted a ``DOMException`` wrapper between layers that mocks didn't
have. Same lesson here: Python's ``httpx.ProxyError`` carries the
status string in ``str(exc)``, but the format could shift between
httpx releases. A live local server reproduces whatever shape the
installed httpx actually produces.
"""

from __future__ import annotations

import http.server
import socket
import threading
from socketserver import ThreadingMixIn

import httpx
import pytest

from spacerouter import (
    AsyncSpaceRouter,
    AuthenticationError,
    NoNodesAvailableError,
    SpaceRouter,
    SpaceRouterError,
)


class _ConnectStatusHandler(http.server.BaseHTTPRequestHandler):
    """Responds to ``CONNECT`` with a configurable status. Set via class var."""

    status = 503
    reason = "Service Unavailable"

    def do_CONNECT(self) -> None:  # noqa: N802 — http.server contract
        self.send_response(self.status, self.reason)
        self.end_headers()
        self.connection.close()

    def log_message(self, *_a: object, **_kw: object) -> None:
        # Silence the per-request stderr line so pytest output stays clean.
        return


class _Server(ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


@pytest.fixture
def connect_proxy():
    """Yields a callable ``(status, reason) -> (server, port)``.

    Each call spawns a fresh local HTTP proxy that responds to CONNECT
    with the requested status. Server is shut down by the test via
    ``srv.shutdown()`` in a try/finally.
    """
    spawned: list[_Server] = []

    def _spawn(status: int, reason: str):
        handler = type(
            "H",
            (_ConnectStatusHandler,),
            {"status": status, "reason": reason},
        )
        # Bind to an OS-assigned free port; close the probe socket
        # before binding the server so the port is reusable.
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        srv = _Server(("127.0.0.1", port), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        spawned.append(srv)
        return srv, port

    yield _spawn

    for srv in spawned:
        try:
            srv.shutdown()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Bug #1 — async client (matches the user-reported smoke repro)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_407_during_connect_raises_authentication_error(connect_proxy):
    srv, port = connect_proxy(407, "Proxy Authentication Required")
    try:
        async with AsyncSpaceRouter(
            "sr_live_invalid", gateway_url=f"http://127.0.0.1:{port}",
        ) as sr:
            with pytest.raises(AuthenticationError) as exc:
                await sr.get("https://example.com")
        assert exc.value.status_code == 407
    finally:
        srv.shutdown()


@pytest.mark.asyncio
async def test_async_503_during_connect_raises_no_nodes_available_error(connect_proxy):
    srv, port = connect_proxy(503, "Service Unavailable")
    try:
        async with AsyncSpaceRouter(
            "sr_live_invalid", gateway_url=f"http://127.0.0.1:{port}",
        ) as sr:
            with pytest.raises(NoNodesAvailableError) as exc:
                await sr.get("https://example.com")
        assert exc.value.status_code == 503
    finally:
        srv.shutdown()


@pytest.mark.asyncio
async def test_async_other_proxy_error_raises_spacerouter_error(connect_proxy):
    """502 (or any other non-2xx CONNECT) must wrap into SpaceRouterError.

    Critically: must NOT leak as ``httpx.ProxyError``. Consumers should
    be able to ``except SpaceRouterError`` without importing httpx.
    """
    srv, port = connect_proxy(502, "Bad Gateway")
    try:
        async with AsyncSpaceRouter(
            "sr_live_invalid", gateway_url=f"http://127.0.0.1:{port}",
        ) as sr:
            with pytest.raises(SpaceRouterError) as exc:
                await sr.get("https://example.com")
        # The whole point of rc.10 #1: no raw httpx exception leaks.
        assert not isinstance(exc.value, httpx.ProxyError)
    finally:
        srv.shutdown()


# ---------------------------------------------------------------------------
# Bug #1 — sync client (same mapping must work end-to-end)
# ---------------------------------------------------------------------------


def test_sync_407_during_connect_raises_authentication_error(connect_proxy):
    srv, port = connect_proxy(407, "Proxy Authentication Required")
    try:
        with SpaceRouter(
            "sr_live_invalid", gateway_url=f"http://127.0.0.1:{port}",
        ) as sr:
            with pytest.raises(AuthenticationError) as exc:
                sr.get("https://example.com")
        assert exc.value.status_code == 407
    finally:
        srv.shutdown()


def test_sync_503_during_connect_raises_no_nodes_available_error(connect_proxy):
    srv, port = connect_proxy(503, "Service Unavailable")
    try:
        with SpaceRouter(
            "sr_live_invalid", gateway_url=f"http://127.0.0.1:{port}",
        ) as sr:
            with pytest.raises(NoNodesAvailableError) as exc:
                sr.get("https://example.com")
        assert exc.value.status_code == 503
    finally:
        srv.shutdown()


def test_sync_other_proxy_error_raises_spacerouter_error(connect_proxy):
    srv, port = connect_proxy(502, "Bad Gateway")
    try:
        with SpaceRouter(
            "sr_live_invalid", gateway_url=f"http://127.0.0.1:{port}",
        ) as sr:
            with pytest.raises(SpaceRouterError) as exc:
                sr.get("https://example.com")
        assert not isinstance(exc.value, httpx.ProxyError)
    finally:
        srv.shutdown()


# ---------------------------------------------------------------------------
# Bug #2 — async cleanup primitives on the SYNC SpaceRouter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_class_async_context_manager_works():
    """Pre-rc.10 raised TypeError on ``async with SpaceRouter(...)``.

    The sync ``SpaceRouter`` lacked ``__aenter__`` / ``__aexit__``;
    consumers in async codebases got a confusing protocol error
    instead of a working client.
    """
    async with SpaceRouter("sr_live_x") as sr:
        assert sr is not None
    # Reaching this line means the async cleanup primitives are wired.


@pytest.mark.asyncio
async def test_sync_class_aclose_is_idempotent():
    sr = SpaceRouter("sr_live_x")
    await sr.aclose()
    await sr.aclose()  # second call must not raise


@pytest.mark.asyncio
async def test_async_class_aclose_is_idempotent():
    sr = AsyncSpaceRouter("sr_live_x")
    await sr.aclose()
    await sr.aclose()  # second call must not raise
