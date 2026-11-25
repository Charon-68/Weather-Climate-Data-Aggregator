"""Ground observation adapter: METAR surface reports from aviationweather.gov (NOAA AWC)."""
import datetime as dt
import math

import httpx

from .common import HTTP_TIMEOUT, IST, USER_AGENT, NoDataError, haversine_km, run_cached

SOURCE = "awc-metar"
URL = "https://aviationweather.gov/api/data/metar"
BOX_DEG = 1.5
MAX_DIST_KM = 250

# Fallback list if the bbox query fails (ICAO, name, lat, lon)
FALLBACK_STATIONS = [
    ("VABB", "Mumbai", 19.0887, 72.8679), ("VIDP", "Delhi", 28.5562, 77.1000),
    ("VOBL", "Bengaluru", 13.1986, 77.7066), ("VOMM", "Chennai", 12.9941, 80.1709),
    ("VECC", "Kolkata", 22.6547, 88.4467), ("VOHS", "Hyderabad", 17.2403, 78.4294),
    ("VAAH", "Ahmedabad", 23.0772, 72.6347), ("VAPO", "Pune", 18.5821, 73.9197),
    ("VIJP", "Jaipur", 26.8242, 75.8122), ("VILK", "Lucknow", 26.7606, 80.8893),
    ("VOGO", "Goa", 15.3808, 73.8314), ("VOTV", "Thiruvananthapuram", 8.4821, 76.9201),
    ("VOCI", "Kochi", 10.1520, 76.4019), ("VEGT", "Guwahati", 26.1061, 91.5859),
    ("VANP", "Nagpur", 21.0922, 79.0472), ("VABP", "Bhopal", 23.2875, 77.3374),
    ("VEPT", "Patna", 25.5913, 85.0880), ("VEBS", "Bhubaneswar", 20.2444, 85.8178),
    ("VIAR", "Amritsar", 31.7096, 74.7973),
]


def _num(v):
    try:
        return float(str(v).rstrip("+"))
    except (TypeError, ValueError):
        return None


def _rh(t, td):
    if t is None or td is None:
        return None
    a, b = 17.625, 243.04
    return round(100 * math.exp(a * td / (b + td)) / math.exp(a * t / (b + t)))


def _ist(epoch):
    return dt.datetime.fromtimestamp(epoch, IST).isoformat(timespec="minutes")


async def _query(client, params):
    r = await client.get(URL, params={**params, "format": "json", "hours": 24})
    if r.status_code == 204 or not r.text.strip():
        return []
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


async def _live(lat: float, lon: float):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        method = "bbox"
        try:
            # Documented order: minLat,minLon,maxLat,maxLon
            bbox = f"{lat - BOX_DEG},{lon - BOX_DEG},{lat + BOX_DEG},{lon + BOX_DEG}"
            obs = await _query(client, {"bbox": bbox})
        except Exception:
            obs = []
            method = "bbox-failed"
        if not obs:
            icao, _, slat, slon = min(FALLBACK_STATIONS, key=lambda s: haversine_km(lat, lon, s[2], s[3]))
            if haversine_km(lat, lon, slat, slon) > MAX_DIST_KM:
                raise NoDataError(f"No METAR station within {MAX_DIST_KM} km of this point")
            obs = await _query(client, {"ids": icao})
            method = f"fallback list ({icao})"

    stations: dict[str, list] = {}
    for o in obs:
        if o.get("icaoId") and o.get("lat") is not None and o.get("obsTime"):
            stations.setdefault(o["icaoId"], []).append(o)
    candidates = []
    for icao, lst in stations.items():
        if any(o.get("temp") is not None for o in lst):
            d = haversine_km(lat, lon, lst[0]["lat"], lst[0]["lon"])
            candidates.append((d, icao))
    if not candidates:
        raise NoDataError("No METAR reports in the last 24 h near this point")
    candidates.sort()
    dist, icao = candidates[0]
    if dist > MAX_DIST_KM:
        raise NoDataError(f"No METAR station within {MAX_DIST_KM} km of this point")

    # de-duplicate by obsTime, sort ascending
    by_time = {o["obsTime"]: o for o in stations[icao]}
    series_raw = [by_time[k] for k in sorted(by_time)]
    latest = series_raw[-1]

    vis_sm = _num(latest.get("visib"))
    vis_plus = str(latest.get("visib", "")).endswith("+")
    wspd = _num(latest.get("wspd"))
    clouds = latest.get("clouds") or []
    data = {
        "station": {
            "icao": icao, "name": latest.get("name"), "lat": latest.get("lat"), "lon": latest.get("lon"),
            "elevation_m": latest.get("elev"), "distance_km": round(dist, 1),
        },
        "latest": {
            "obs_time_ist": _ist(latest["obsTime"]),
            "temp": latest.get("temp"), "dewpoint": latest.get("dewp"),
            "rh": _rh(latest.get("temp"), latest.get("dewp")),
            "wind_dir": latest.get("wdir"), "wind_kt": wspd,
            "wind_kmh": None if wspd is None else round(wspd * 1.852),
            "gust_kt": latest.get("wgst"),
            "visibility_km": None if vis_sm is None else round(vis_sm * 1.609, 1),
            "visibility_plus": vis_plus,
            "pressure_hpa": latest.get("altim"),
            "weather": latest.get("wxString"),
            "clouds": ", ".join(f"{c.get('cover')} {c.get('base') or ''}".strip() for c in clouds) or latest.get("cover"),
            "flight_category": latest.get("fltCat"),
            "raw": latest.get("rawOb"),
        },
        "series": [
            {"time_ist": _ist(o["obsTime"]), "temp": o.get("temp"), "dewpoint": o.get("dewp")}
            for o in series_raw
        ],
        "nearby": [
            {"icao": i, "distance_km": round(d, 1), "lat": stations[i][0]["lat"], "lon": stations[i][0]["lon"],
             "name": stations[i][0].get("name")}
            for d, i in candidates[:6]
        ],
        "method": method,
    }
    units = {"temp": "°C", "dewpoint": "°C", "rh": "%", "wind": "kt / km/h", "wind_dir": "° (from)",
             "visibility": "km", "pressure": "hPa", "distance": "km"}
    return data, units


async def fetch(lat: float, lon: float, offline: bool = False) -> dict:
    return await run_cached(SOURCE, lat, lon, _live, offline)
