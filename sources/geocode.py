"""Geocoding adapter: Open-Meteo geocoding API (GeoNames-based)."""
import httpx

from .common import HTTP_TIMEOUT, USER_AGENT, envelope

SOURCE = "open-meteo-geocoding"
URL = "https://geocoding-api.open-meteo.com/v1/search"


async def fetch(q: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(URL, params={"name": q, "count": 5, "language": "en", "format": "json"})
        r.raise_for_status()
        results = [
            {
                "name": x.get("name"), "admin1": x.get("admin1"), "country": x.get("country"),
                "lat": x.get("latitude"), "lon": x.get("longitude"), "elevation": x.get("elevation"),
            }
            for x in r.json().get("results", []) or []
        ]
        return envelope(SOURCE, "ok", {"results": results}, {"elevation": "m"})
    except Exception as e:
        return envelope(SOURCE, "error", {"results": []}, error=f"{type(e).__name__}: {e}")
