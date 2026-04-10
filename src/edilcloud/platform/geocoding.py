from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeocodingResult:
    latitude: float
    longitude: float
    formatted_address: str | None = None
    provider: str = "nominatim"


def geocode_address(address: str | None) -> GeocodingResult | None:
    normalized_address = (address or "").strip()
    if not normalized_address:
        return None

    provider = str(getattr(settings, "GEOCODING_PROVIDER", "nominatim") or "nominatim").strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider != "nominatim":
        logger.warning("Unsupported geocoding provider '%s', skipping lookup.", provider)
        return None

    params = urlencode(
        {
            "q": normalized_address,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 0,
        }
    )
    request = Request(
        f"{getattr(settings, 'GEOCODING_NOMINATIM_URL', 'https://nominatim.openstreetmap.org/search').rstrip('/')}?{params}",
        headers={
            "Accept": "application/json",
            "User-Agent": getattr(
                settings,
                "GEOCODING_USER_AGENT",
                "EdilCloud/0.1 (local-dev geocoding)",
            ),
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=float(getattr(settings, "GEOCODING_TIMEOUT_SECONDS", 4.0))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Geocoding lookup failed for '%s': %s", normalized_address, exc)
        return None

    if not isinstance(payload, list) or not payload:
        return None

    top_hit = payload[0] or {}
    try:
        latitude = round(float(top_hit["lat"]), 6)
        longitude = round(float(top_hit["lon"]), 6)
    except (KeyError, TypeError, ValueError):
        return None

    display_name = top_hit.get("display_name")
    return GeocodingResult(
        latitude=latitude,
        longitude=longitude,
        formatted_address=display_name.strip() if isinstance(display_name, str) and display_name.strip() else None,
        provider="nominatim",
    )
