"""Shared helpers: normalized result envelope, in-memory TTL cache, disk cache fallback."""
import datetime as dt
import json
import math
import time
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
TTL_SECONDS = 600  # 10 minutes
HTTP_TIMEOUT = 25.0
USER_AGENT = "open-weather-climate-aggregator/0.1 (prototype)"

_mem: dict[str, tuple[float, dict]] = {}


class NoDataError(Exception):
    """Raised when a source answered but has nothing for this location."""


def now_iso() -> str:
    return dt.datetime.now(IST).isoformat(timespec="seconds")


def envelope(source, status, data=None, units=None, error=None, fetched_at=None) -> dict:
    return {
        "source": source,
        "status": status,  # "ok" | "error" | "cached"
        "fetched_at": fetched_at or now_iso(),
        "units": units or {},
        "data": data,
        "error": error,
    }


def _key(source: str, lat: float, lon: float) -> str:
    return f"{source}_{lat:.2f}_{lon:.2f}"


def _err_text(e: Exception) -> str:
    msg = str(e).strip()
    return f"{type(e).__name__}: {msg}" if msg else type(e).__name__


async def run_cached(source: str, lat: float, lon: float, live_fn, offline: bool = False) -> dict:
    """Memory cache -> live fetch -> disk fallback. Never raises."""
    key = _key(source, lat, lon)
    path = CACHE_DIR / f"{key}.json"

    if offline:
        err = "Simulated outage: live fetch skipped"
    else:
        hit = _mem.get(key)
        if hit and time.time() - hit[0] < TTL_SECONDS:
            return hit[1]
        try:
            data, units = await live_fn(lat, lon)
            res = envelope(source, "ok", data, units)
            _mem[key] = (time.time(), res)
            try:
                path.write_text(json.dumps(res))
            except Exception:
                pass
            return res
        except NoDataError as e:
            # Source is reachable but has no data here: do not mask with stale cache.
            return envelope(source, "error", error=str(e))
        except Exception as e:  # network, HTTP, parsing ... anything
            err = _err_text(e)

    if path.exists():
        try:
            res = json.loads(path.read_text())
            res["status"] = "cached"
            res["error"] = f"Live fetch failed ({err}). Showing disk copy from {res.get('fetched_at')}."
            return res
        except Exception:
            pass
    return envelope(source, "error", error=err)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
