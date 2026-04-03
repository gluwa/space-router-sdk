"""Tests for the SpaceRouter proxy client."""

import httpx
import pytest
import respx

from spacerouter import (
    AsyncSpaceRouter,
    SpaceRouter,
)
from spacerouter.client import _build_proxy, _check_proxy_errors, _validate_region
from spacerouter.exceptions import (
    AuthenticationError,
    NoNodesAvailableError,
    RateLimitError,
    UpstreamError,
)
from spacerouter.models import ProxyResponse


# ---------------------------------------------------------------------------
# _build_proxy
# ---------------------------------------------------------------------------


class TestBuildProxy:
    def test_http_default(self):
        result = _build_proxy("sr_live_abc", "http://gw:8080", "http", None)
        assert isinstance(result, httpx.Proxy)
        assert str(result.url) == "http://gw:8080"
        assert "proxy-authorization" in result.headers

    def test_socks5(self):
        result = _build_proxy("sr_live_abc", "socks5://gw:1080", "socks5", None)
        assert result == "socks5://sr_live_abc:@gw:1080"

    def test_default_ports(self):
        result = _build_proxy("key", "http://gw", "http", None)
        assert isinstance(result, httpx.Proxy)
        assert str(result.url) == "http://gw:8080"

        result = _build_proxy("key", "socks5://gw", "socks5", None)
        assert result == "socks5://key:@gw:1080"

    def test_with_routing_headers(self):
        result = _build_proxy("key", "http://gw:8080", "http", "US")
        assert isinstance(result, httpx.Proxy)

    def test_without_routing_returns_proxy(self):
        result = _build_proxy("key", "http://gw:8080", "http", None)
        assert isinstance(result, httpx.Proxy)

    def test_rejects_invalid_region(self):
        with pytest.raises(ValueError, match="2-letter country code"):
            _build_proxy("key", "http://gw:8080", "http", "Seoul, KR")
        with pytest.raises(ValueError, match="2-letter country code"):
            _build_proxy("key", "http://gw:8080", "http", "USA")
        with pytest.raises(ValueError, match="2-letter country code"):
            _build_proxy("key", "http://gw:8080", "http", "u")

    def test_ip_type_header(self):
        result = _build_proxy("key", "http://gw:8080", "http", None, "residential")
        assert isinstance(result, httpx.Proxy)

    def test_region_and_ip_type_headers(self):
        result = _build_proxy("key", "http://gw:8080", "http", "US", "mobile")
        assert isinstance(result, httpx.Proxy)

    def test_no_ip_type_returns_proxy(self):
        result = _build_proxy("key", "http://gw:8080", "http", None, None)
        assert isinstance(result, httpx.Proxy)


class TestValidateRegion:
    def test_valid_codes(self):
        for code in ("US", "KR", "JP", "DE", "BR"):
            _validate_region(code)  # should not raise

    @pytest.mark.parametrize("bad", ["Seoul, KR", "USA", "u", "us", "123", ""])
    def test_invalid_codes(self, bad):
        with pytest.raises(ValueError, match="2-letter country code"):
            _validate_region(bad)


# ---------------------------------------------------------------------------
# _check_proxy_errors
# ---------------------------------------------------------------------------


class TestCheckProxyErrors:
    def _make_response(
        self, status_code: int, headers: dict | None = None, json_body: dict | None = None
    ) -> httpx.Response:
        content = b""
        resp_headers = dict(headers or {})
        if json_body is not None:
            import json
            content = json.dumps(json_body).encode()
            resp_headers["content-type"] = "application/json"
        return httpx.Response(status_code, headers=resp_headers, content=content)

    def test_407_raises_authentication_error(self):
        resp = self._make_response(
            407, headers={"x-spacerouter-request-id": "req-1"}
        )
        with pytest.raises(AuthenticationError) as exc_info:
            _check_proxy_errors(resp)
        assert exc_info.value.status_code == 407
        assert exc_info.value.request_id == "req-1"

    def test_429_raises_rate_limit_error(self):
        resp = self._make_response(
            429,
            headers={"retry-after": "42", "x-spacerouter-request-id": "req-2"},
        )
        with pytest.raises(RateLimitError) as exc_info:
            _check_proxy_errors(resp)
        assert exc_info.value.retry_after == 42
        assert exc_info.value.request_id == "req-2"

    def test_429_defaults_retry_after_to_60(self):
        resp = self._make_response(429)
        with pytest.raises(RateLimitError) as exc_info:
            _check_proxy_errors(resp)
        assert exc_info.value.retry_after == 60

    def test_502_raises_upstream_error(self):
        resp = self._make_response(
            502,
            headers={
                "x-spacerouter-request-id": "req-3",
            },
        )
        with pytest.raises(UpstreamError) as exc_info:
            _check_proxy_errors(resp)
        assert exc_info.value.request_id == "req-3"

    def test_503_no_nodes(self):
        resp = self._make_response(
            503,
            json_body={"error": "no_nodes_available", "message": "..."},
        )
        with pytest.raises(NoNodesAvailableError):
            _check_proxy_errors(resp)

    def test_503_other_passes_through(self):
        resp = self._make_response(
            503, json_body={"error": "something_else", "message": "..."}
        )
        _check_proxy_errors(resp)  # should NOT raise

    def test_200_passes_through(self):
        resp = self._make_response(200)
        _check_proxy_errors(resp)  # should NOT raise

    def test_404_from_target_passes_through(self):
        resp = self._make_response(404)
        _check_proxy_errors(resp)  # target 404 is not a proxy error


# ---------------------------------------------------------------------------
# ProxyResponse
# ---------------------------------------------------------------------------


class TestProxyResponse:
    def test_request_id(self):
        raw = httpx.Response(200, headers={"x-spacerouter-request-id": "r-1"})
        resp = ProxyResponse(raw)
        assert resp.request_id == "r-1"

    def test_missing_headers_return_none(self):
        raw = httpx.Response(200)
        resp = ProxyResponse(raw)
        assert resp.request_id is None

    def test_delegates_status_code(self):
        raw = httpx.Response(201)
        resp = ProxyResponse(raw)
        assert resp.status_code == 201

    def test_delegates_text(self):
        raw = httpx.Response(200, text="hello")
        resp = ProxyResponse(raw)
        assert resp.text == "hello"

    def test_repr(self):
        raw = httpx.Response(200)
        resp = ProxyResponse(raw)
        assert "200" in repr(resp)


# ---------------------------------------------------------------------------
# SpaceRouter (sync) integration
# ---------------------------------------------------------------------------


class TestSpaceRouter:
    def test_default_gateway(self):
        client = SpaceRouter("sr_live_test")
        assert client._gateway_url == "https://gateway.spacerouter.org:8080"
        assert client._protocol == "http"
        client.close()

    def test_socks5_protocol(self):
        client = SpaceRouter(
            "sr_live_test",
            protocol="socks5",
            gateway_url="socks5://gw:1080",
        )
        assert client._protocol == "socks5"
        client.close()

    def test_context_manager(self):
        with SpaceRouter("sr_live_test") as client:
            assert isinstance(client, SpaceRouter)

    def test_repr(self):
        client = SpaceRouter("sr_live_test", gateway_url="http://gw:8080")
        assert "http://gw:8080" in repr(client)
        client.close()

    def test_with_routing_returns_new_client(self):
        client = SpaceRouter("sr_live_test")
        routed = client.with_routing(region="KR")
        assert routed is not client
        assert routed._region == "KR"
        client.close()
        routed.close()

    @respx.mock
    def test_get_success(self):
        respx.get("http://example.com/").mock(
            return_value=httpx.Response(
                200,
                text="ok",
                headers={
                    "x-spacerouter-request-id": "req-1",
                },
            )
        )
        with SpaceRouter("sr_live_test") as client:
            resp = client.get("http://example.com/")
            assert resp.status_code == 200
            assert resp.text == "ok"
            assert resp.request_id == "req-1"

    @respx.mock
    def test_post(self):
        respx.post("http://example.com/data").mock(
            return_value=httpx.Response(201, json={"id": 1})
        )
        with SpaceRouter("sr_live_test") as client:
            resp = client.post("http://example.com/data", json={"value": "x"})
            assert resp.status_code == 201

    @respx.mock
    def test_407_raises(self):
        respx.get("http://example.com/").mock(
            return_value=httpx.Response(407)
        )
        with SpaceRouter("sr_live_test") as client:
            with pytest.raises(AuthenticationError):
                client.get("http://example.com/")


# ---------------------------------------------------------------------------
# AsyncSpaceRouter
# ---------------------------------------------------------------------------


class TestAsyncSpaceRouter:
    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with AsyncSpaceRouter("sr_live_test") as client:
            assert isinstance(client, AsyncSpaceRouter)

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_success(self):
        respx.get("http://example.com/").mock(
            return_value=httpx.Response(200, text="ok")
        )
        async with AsyncSpaceRouter("sr_live_test") as client:
            resp = await client.get("http://example.com/")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_raises(self):
        respx.get("http://example.com/").mock(
            return_value=httpx.Response(429, headers={"retry-after": "10"})
        )
        async with AsyncSpaceRouter("sr_live_test") as client:
            with pytest.raises(RateLimitError) as exc_info:
                await client.get("http://example.com/")
            assert exc_info.value.retry_after == 10


# ---------------------------------------------------------------------------
# IP-type routing
# ---------------------------------------------------------------------------


class TestListRegions:
    @respx.mock
    def test_list_regions_success(self):
        respx.get("https://coordination.spacerouter.org/regions").mock(
            return_value=httpx.Response(200, json={
                "regions": [{"region": "US", "ip_types": ["residential", "mobile"]}],
                "brightdata_available": True,
            })
        )
        with SpaceRouter("sr_live_test") as client:
            result = client.list_regions()
            assert len(result.regions) == 1
            assert result.regions[0].region == "US"
            assert result.brightdata_available is True

    @respx.mock
    def test_list_regions_with_ip_type_filter(self):
        respx.get("https://coordination.spacerouter.org/regions").mock(
            return_value=httpx.Response(200, json={
                "regions": [{"region": "KR", "ip_types": ["residential"]}],
                "brightdata_available": False,
            })
        )
        with SpaceRouter("sr_live_test") as client:
            result = client.list_regions(ip_type="residential")
            assert len(result.regions) == 1

    @respx.mock
    def test_list_regions_empty(self):
        respx.get("https://coordination.spacerouter.org/regions").mock(
            return_value=httpx.Response(200, json={
                "regions": [],
                "brightdata_available": False,
            })
        )
        with SpaceRouter("sr_live_test") as client:
            result = client.list_regions()
            assert result.regions == []

    @respx.mock
    def test_list_regions_error(self):
        mock_resp = httpx.Response(500, text="Internal Error")
        mock_resp.request = httpx.Request("GET", "https://coordination.spacerouter.org/regions")
        respx.get("https://coordination.spacerouter.org/regions").mock(return_value=mock_resp)
        with SpaceRouter("sr_live_test") as client:
            with pytest.raises(httpx.HTTPStatusError):
                client.list_regions()

    @pytest.mark.asyncio
    @respx.mock
    async def test_async_list_regions(self):
        respx.get("https://coordination.spacerouter.org/regions").mock(
            return_value=httpx.Response(200, json={
                "regions": [{"region": "DE", "ip_types": ["hosting"]}],
                "brightdata_available": True,
            })
        )
        async with AsyncSpaceRouter("sr_live_test") as client:
            result = await client.list_regions()
            assert len(result.regions) == 1


class TestIpTypeRouting:
    def test_ip_type_stored(self):
        client = SpaceRouter("sr_live_test", ip_type="residential")
        assert client._ip_type == "residential"
        client.close()

    def test_with_routing_passes_ip_type(self):
        client = SpaceRouter("sr_live_test")
        routed = client.with_routing(ip_type="mobile")
        assert routed._ip_type == "mobile"
        client.close()
        routed.close()

    def test_with_routing_passes_both(self):
        client = SpaceRouter("sr_live_test")
        routed = client.with_routing(region="US", ip_type="datacenter")
        assert routed._region == "US"
        assert routed._ip_type == "datacenter"
        client.close()
        routed.close()
