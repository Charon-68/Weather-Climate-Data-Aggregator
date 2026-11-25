"""NWP forecast adapter: Open-Meteo (blend + GFS / ECMWF IFS / ICON model comparison)."""
import asyncio

import httpx

from .common import HTTP_TIMEOUT, USER_AGENT, run_cached

SOURCE = "open-meteo-forecast"
BASE = "https://api.open-meteo.com/v1/forecast"
MODELS = {
    "gfs_seamless": "GFS (NOAA, USA)",
    "ecmwf_ifs025": "ECMWF IFS 0.25°",
    "icon_seamless": "ICON (DWD, Germany)",
}
TZ = "Asia/Kolkata"


async def _get(client: httpx.AsyncClient, params: dict) -> dict:
    r = await client.get(BASE, params=params)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    if j.get("error"):
        raise RuntimeError(j.get("reason", "Open-Meteo error"))
    return j


async def _model_comparison(client, lat, lon) -> dict:
    base = {
        "latitude": lat, "longitude": lon, "hourly": "temperature_2m,precipitation",
        "timezone": TZ, "forecast_days": 7,
    }
    responses: dict[str, dict] = {}
    dropped: dict[str, str] = {}
    try:
        j = await _get(client, {**base, "models": ",".join(MODELS)})
        responses = {m: j for m in MODELS}
    except Exception:
        # One model name failed? Try each individually and keep the ones that work.
        results = await asyncio.gather(
            *[_get(client, {**base, "models": m}) for m in MODELS], return_exceptions=True
        )
        for m, res in zip(MODELS, results):
            if isinstance(res, Exception):
                dropped[m] = str(res)[:150]
            else:
                responses[m] = res

    out = {"time": None, "series": {}, "dropped": dropped}
    for m, j in responses.items():
        h = j.get("hourly", {})
        temp = h.get(f"temperature_2m_{m}", h.get("temperature_2m"))
        prcp = h.get(f"precipitation_{m}", h.get("precipitation"))
        if not temp or all(v is None for v in temp):
            dropped[m] = "no data for this location"
            continue
        out["time"] = out["time"] or h.get("time")
        out["series"][m] = {"label": MODELS[m], "temperature_2m": temp, "precipitation": prcp}
    if not out["series"]:
        raise RuntimeError("all models failed")
    return out


async def _live(lat: float, lon: float):
    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,cloud_cover",
        "hourly": "temperature_2m,precipitation,relative_humidity_2m,wind_speed_10m,shortwave_radiation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": TZ, "forecast_days": 7,
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        main, models = await asyncio.gather(
            _get(client, params), _model_comparison(client, lat, lon), return_exceptions=True
        )
    if isinstance(main, Exception):
        raise main

    data = {
        "model": "Open-Meteo best-match blend",
        "grid_lat": main.get("latitude"), "grid_lon": main.get("longitude"),
        "elevation_m": main.get("elevation"),
        "timezone": main.get("timezone"),
        "current": main.get("current"),
        "daily": main.get("daily"),
        "hourly": main.get("hourly"),
        "models": None if isinstance(models, Exception) else models,
        "models_error": str(models) if isinstance(models, Exception) else None,
    }
    units = {
        "current": main.get("current_units", {}),
        "daily": main.get("daily_units", {}),
        "hourly": main.get("hourly_units", {}),
    }
    return data, units


async def fetch(lat: float, lon: float, offline: bool = False) -> dict:
    return await run_cached(SOURCE, lat, lon, _live, offline)
