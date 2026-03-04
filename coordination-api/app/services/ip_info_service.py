"""IP classification service using ipinfo.io.

Given an IP address, determines:
  - ip_type: "residential", "mobile", "datacenter", or "business"
  - ip_region: "{city}, {country}" (e.g., "Seoul, KR")
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_IPINFO_BASE = "https://ipinfo.io"


@dataclass
class IPClassification:
    ip_type: str  # "residential", "mobile", "datacenter", "business"
    ip_region: str  # e.g., "Seoul, KR"


class IPInfoService:
    """Classifies IP addresses using ipinfo.io."""

    def __init__(self, http_client: httpx.AsyncClient, token: str = "") -> None:
        self._client = http_client
        self._token = token

    async def classify(self, ip: str) -> Optional[IPClassification]:
        """Look up IP type and region. Returns None on failure."""
        if not ip:
            return None

        try:
            params = {}
            if self._token:
                params["token"] = self._token

            resp = await self._client.get(
                f"{_IPINFO_BASE}/{ip}/json",
                params=params,
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

            ip_type = self._determine_ip_type(data)
            ip_region = self._determine_region(data)

            logger.info(
                "IP classification for %s: type=%s region=%s",
                ip, ip_type, ip_region,
            )
            return IPClassification(ip_type=ip_type, ip_region=ip_region)

        except Exception as exc:
            logger.warning("IP classification failed for %s: %s", ip, exc)
            return None

    def _determine_ip_type(self, data: dict) -> str:
        """Determine IP type from ipinfo.io response.

        With a token, ipinfo returns a ``privacy`` object with boolean
        fields ``hosting``, ``proxy``, ``vpn``, ``tor``, and optionally
        a ``company.type`` field ("isp", "hosting", "business", "education").

        Without a token, we fall back to heuristics on the ``org`` field.
        """
        # Check privacy object (available with token)
        privacy = data.get("privacy", {})
        if privacy:
            if privacy.get("hosting"):
                return "datacenter"
            if privacy.get("vpn") or privacy.get("proxy") or privacy.get("tor"):
                return "datacenter"

        # Check company type (available with token)
        company = data.get("company", {})
        company_type = company.get("type", "")
        if company_type == "hosting":
            return "datacenter"
        if company_type == "business":
            return "business"
        if company_type == "isp":
            # ISP could be residential or mobile — check carrier info
            carrier = data.get("carrier", {})
            if carrier:
                return "mobile"
            return "residential"

        # Fallback: heuristics from org/ASN field
        org = data.get("org", "").lower()
        if any(kw in org for kw in ("hosting", "cloud", "server", "data center", "datacenter", "amazon", "google", "microsoft", "digitalocean", "linode", "vultr", "hetzner", "ovh")):
            return "datacenter"
        if any(kw in org for kw in ("mobile", "wireless", "cellular")):
            return "mobile"

        # Default to residential for ISP-like orgs
        return "residential"

    def _determine_region(self, data: dict) -> str:
        """Build region string from city and country."""
        city = data.get("city", "")
        country = data.get("country", "")

        if city and country:
            return f"{city}, {country}"
        if country:
            return country
        return "unknown"
