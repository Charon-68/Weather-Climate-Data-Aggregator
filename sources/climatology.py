"""Climatology adapter: NASA POWER monthly long-term means (MERRA-2 + CERES)."""
import httpx

from .common import HTTP_TIMEOUT, USER_AGENT, NoDataError, run_cached

SOURCE = "nasa-power-climatology"
URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"
PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN", "WS10M"]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
DAYS = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


async def _live(lat: float, lon: float):
    q = {
        "parameters": ",".join(PARAMS), "community": "RE",
        "longitude": round(lon, 4), "latitude": round(lat, 4), "format": "JSON",
    }
    async with httpx.AsyncClient(timeout=40.0, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(URL, params=q)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    header = j.get("header", {})
    fill = header.get("fill_value", -999.0)
    raw = j["properties"]["parameter"]
    meta = j.get("parameters", {})

    params, units = {}, {}
    for p in PARAMS:
        vals = raw.get(p, {})
        monthly = [None if vals.get(m) in (None, fill) else vals.get(m) for m in MONTHS]
        ann = vals.get("ANN")
        params[p] = {
            "longname": meta.get(p, {}).get("longname", p),
            "monthly": monthly,
            "annual": None if ann in (None, fill) else ann,
        }
        units[p] = meta.get(p, {}).get("units", "")
    if all(v is None for v in params["T2M"]["monthly"]):
        raise NoDataError("NASA POWER returned only fill values for this point")

    # Derived: monthly precipitation total in mm (from mm/day)
    pr = params["PRECTOTCORR"]["monthly"]
    params["PRECIP_MONTH_MM"] = {
        "longname": "Precipitation, monthly total (derived)",
        "monthly": [None if v is None else round(v * d, 1) for v, d in zip(pr, DAYS)],
        "annual": None if params["PRECTOTCORR"]["annual"] is None else round(params["PRECTOTCORR"]["annual"] * 365.25),
    }
    units["PRECIP_MONTH_MM"] = "mm/month"

    data = {
        "months": MONTHS,
        "period": header.get("range"),
        "datasets": header.get("sources"),
        "api_version": header.get("api", {}).get("version"),
        "params": params,
    }
    return data, units


async def fetch(lat: float, lon: float, offline: bool = False) -> dict:
    return await run_cached(SOURCE, lat, lon, _live, offline)
