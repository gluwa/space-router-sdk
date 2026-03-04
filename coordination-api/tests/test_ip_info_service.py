"""Tests for the IP classification service (ipinfo.io)."""

import httpx
import pytest
import respx
from httpx import Response

from app.services.ip_info_service import IPInfoService


@pytest.fixture
def service():
    client = httpx.AsyncClient()
    return IPInfoService(client, token="test-token")


class TestClassify:
    @pytest.mark.asyncio
    @respx.mock
    async def test_residential_ip(self, service):
        respx.get("https://ipinfo.io/1.2.3.4/json").mock(
            return_value=Response(200, json={
                "ip": "1.2.3.4",
                "city": "Seoul",
                "region": "Seoul",
                "country": "KR",
                "org": "AS4766 Korea Telecom",
                "privacy": {
                    "vpn": False,
                    "proxy": False,
                    "tor": False,
                    "relay": False,
                    "hosting": False,
                },
                "company": {"type": "isp"},
            })
        )

        result = await service.classify("1.2.3.4")
        assert result is not None
        assert result.ip_type == "residential"
        assert result.ip_region == "Seoul, KR"

    @pytest.mark.asyncio
    @respx.mock
    async def test_datacenter_ip_via_privacy(self, service):
        respx.get("https://ipinfo.io/5.6.7.8/json").mock(
            return_value=Response(200, json={
                "ip": "5.6.7.8",
                "city": "Ashburn",
                "country": "US",
                "org": "AS14618 Amazon.com, Inc.",
                "privacy": {
                    "vpn": False,
                    "proxy": False,
                    "tor": False,
                    "relay": False,
                    "hosting": True,
                },
            })
        )

        result = await service.classify("5.6.7.8")
        assert result is not None
        assert result.ip_type == "datacenter"
        assert result.ip_region == "Ashburn, US"

    @pytest.mark.asyncio
    @respx.mock
    async def test_datacenter_ip_via_company_type(self, service):
        respx.get("https://ipinfo.io/10.0.0.1/json").mock(
            return_value=Response(200, json={
                "ip": "10.0.0.1",
                "city": "Frankfurt",
                "country": "DE",
                "org": "AS24940 Hetzner Online GmbH",
                "company": {"type": "hosting"},
            })
        )

        result = await service.classify("10.0.0.1")
        assert result is not None
        assert result.ip_type == "datacenter"
        assert result.ip_region == "Frankfurt, DE"

    @pytest.mark.asyncio
    @respx.mock
    async def test_mobile_ip_via_carrier(self, service):
        respx.get("https://ipinfo.io/2.3.4.5/json").mock(
            return_value=Response(200, json={
                "ip": "2.3.4.5",
                "city": "Busan",
                "country": "KR",
                "org": "AS3786 LG DACOM Corporation",
                "company": {"type": "isp"},
                "carrier": {"name": "LG U+", "mcc": "450", "mnc": "06"},
            })
        )

        result = await service.classify("2.3.4.5")
        assert result is not None
        assert result.ip_type == "mobile"
        assert result.ip_region == "Busan, KR"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fallback_org_heuristic_datacenter(self, service):
        """Without privacy/company fields, falls back to org keyword matching."""
        respx.get("https://ipinfo.io/9.9.9.9/json").mock(
            return_value=Response(200, json={
                "ip": "9.9.9.9",
                "city": "Portland",
                "country": "US",
                "org": "AS15169 Google LLC",
            })
        )

        result = await service.classify("9.9.9.9")
        assert result is not None
        assert result.ip_type == "datacenter"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fallback_org_heuristic_residential(self, service):
        """Unknown ISP org defaults to residential."""
        respx.get("https://ipinfo.io/3.4.5.6/json").mock(
            return_value=Response(200, json={
                "ip": "3.4.5.6",
                "city": "Incheon",
                "country": "KR",
                "org": "AS4766 Korea Telecom",
            })
        )

        result = await service.classify("3.4.5.6")
        assert result is not None
        assert result.ip_type == "residential"
        assert result.ip_region == "Incheon, KR"

    @pytest.mark.asyncio
    @respx.mock
    async def test_api_failure_returns_none(self, service):
        respx.get("https://ipinfo.io/1.1.1.1/json").mock(
            return_value=Response(429, text="Rate limited")
        )

        result = await service.classify("1.1.1.1")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_ip_returns_none(self, service):
        result = await service.classify("")
        assert result is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_region_country_only(self, service):
        respx.get("https://ipinfo.io/7.7.7.7/json").mock(
            return_value=Response(200, json={
                "ip": "7.7.7.7",
                "country": "KR",
                "org": "AS4766 Korea Telecom",
            })
        )

        result = await service.classify("7.7.7.7")
        assert result is not None
        assert result.ip_region == "KR"

    @pytest.mark.asyncio
    @respx.mock
    async def test_token_passed_as_param(self):
        route = respx.get("https://ipinfo.io/1.2.3.4/json").mock(
            return_value=Response(200, json={
                "ip": "1.2.3.4",
                "city": "Seoul",
                "country": "KR",
                "org": "AS4766 Korea Telecom",
            })
        )

        client = httpx.AsyncClient()
        svc = IPInfoService(client, token="my-secret-token")
        await svc.classify("1.2.3.4")

        assert route.called
        req = route.calls[0].request
        assert "token=my-secret-token" in str(req.url)

    # --- Missing branch coverage below ---

    @pytest.mark.asyncio
    @respx.mock
    async def test_datacenter_via_vpn_privacy(self, service):
        """privacy.vpn=True should classify as datacenter."""
        respx.get("https://ipinfo.io/11.11.11.11/json").mock(
            return_value=Response(200, json={
                "ip": "11.11.11.11",
                "city": "Amsterdam",
                "country": "NL",
                "org": "AS9009 M247 Ltd",
                "privacy": {
                    "vpn": True,
                    "proxy": False,
                    "tor": False,
                    "relay": False,
                    "hosting": False,
                },
            })
        )

        result = await service.classify("11.11.11.11")
        assert result is not None
        assert result.ip_type == "datacenter"

    @pytest.mark.asyncio
    @respx.mock
    async def test_datacenter_via_proxy_privacy(self, service):
        """privacy.proxy=True should classify as datacenter."""
        respx.get("https://ipinfo.io/12.12.12.12/json").mock(
            return_value=Response(200, json={
                "ip": "12.12.12.12",
                "city": "London",
                "country": "GB",
                "org": "AS20473 Vultr Holdings",
                "privacy": {
                    "vpn": False,
                    "proxy": True,
                    "tor": False,
                    "relay": False,
                    "hosting": False,
                },
            })
        )

        result = await service.classify("12.12.12.12")
        assert result is not None
        assert result.ip_type == "datacenter"

    @pytest.mark.asyncio
    @respx.mock
    async def test_datacenter_via_tor_privacy(self, service):
        """privacy.tor=True should classify as datacenter."""
        respx.get("https://ipinfo.io/13.13.13.13/json").mock(
            return_value=Response(200, json={
                "ip": "13.13.13.13",
                "city": "Berlin",
                "country": "DE",
                "org": "AS24940 Hetzner",
                "privacy": {
                    "vpn": False,
                    "proxy": False,
                    "tor": True,
                    "relay": False,
                    "hosting": False,
                },
            })
        )

        result = await service.classify("13.13.13.13")
        assert result is not None
        assert result.ip_type == "datacenter"

    @pytest.mark.asyncio
    @respx.mock
    async def test_business_ip_via_company_type(self, service):
        """company.type='business' should classify as business."""
        respx.get("https://ipinfo.io/14.14.14.14/json").mock(
            return_value=Response(200, json={
                "ip": "14.14.14.14",
                "city": "San Jose",
                "country": "US",
                "org": "AS2906 Netflix Inc.",
                "company": {"type": "business"},
            })
        )

        result = await service.classify("14.14.14.14")
        assert result is not None
        assert result.ip_type == "business"

    @pytest.mark.asyncio
    @respx.mock
    async def test_mobile_via_org_heuristic(self, service):
        """Org containing 'mobile'/'wireless'/'cellular' → mobile."""
        respx.get("https://ipinfo.io/15.15.15.15/json").mock(
            return_value=Response(200, json={
                "ip": "15.15.15.15",
                "city": "Dallas",
                "country": "US",
                "org": "AS21928 T-Mobile USA Inc. Wireless",
            })
        )

        result = await service.classify("15.15.15.15")
        assert result is not None
        assert result.ip_type == "mobile"

    @pytest.mark.asyncio
    @respx.mock
    async def test_region_unknown_when_no_city_no_country(self, service):
        """No city and no country → region='unknown'."""
        respx.get("https://ipinfo.io/16.16.16.16/json").mock(
            return_value=Response(200, json={
                "ip": "16.16.16.16",
                "org": "AS4766 Korea Telecom",
            })
        )

        result = await service.classify("16.16.16.16")
        assert result is not None
        assert result.ip_region == "unknown"

    @pytest.mark.asyncio
    @respx.mock
    async def test_network_error_returns_none(self, service):
        """Connection errors should return None, not raise."""
        respx.get("https://ipinfo.io/17.17.17.17/json").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await service.classify("17.17.17.17")
        assert result is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_token_omits_param(self):
        """When token is empty, no token param in the URL."""
        route = respx.get("https://ipinfo.io/1.2.3.4/json").mock(
            return_value=Response(200, json={
                "ip": "1.2.3.4",
                "city": "Seoul",
                "country": "KR",
                "org": "AS4766 Korea Telecom",
            })
        )

        client = httpx.AsyncClient()
        svc = IPInfoService(client, token="")
        await svc.classify("1.2.3.4")

        assert route.called
        req = route.calls[0].request
        assert "token=" not in str(req.url)
