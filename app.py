"""Open Weather & Climate Aggregator: FastAPI backend.

Sources -> Adapters (normalize) -> Cache (memory + disk) -> FastAPI -> Web UI
"""
import asyncio
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sources import climatology, forecast, geocode, observations
from sources.common import now_iso

ROOT = Path(__file__).resolve().parent
app = FastAPI(
    title="Open Weather & Climate Aggregator",
    description="Prototype: aggregates NWP forecasts, climatology, ground observations (and satellite tiles in the UI).",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

ADAPTERS = {
    "forecast": forecast.fetch,
    "climatology": climatology.fetch,
    "observations": observations.fetch,
}

Lat = Query(..., ge=-90, le=90)
Lon = Query(..., ge=-180, le=180)
Offline = Query(False, description="Simulate an outage: skip live fetch, serve disk cache")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/geocode")
async def api_geocode(q: str = Query(..., min_length=1)):
    return await geocode.fetch(q)


@app.get("/api/forecast")
async def api_forecast(lat: float = Lat, lon: float = Lon, offline: bool = Offline):
    return await forecast.fetch(lat, lon, offline)


@app.get("/api/climatology")
async def api_climatology(lat: float = Lat, lon: float = Lon, offline: bool = Offline):
    return await climatology.fetch(lat, lon, offline)


@app.get("/api/observations")
async def api_observations(lat: float = Lat, lon: float = Lon, offline: bool = Offline):
    return await observations.fetch(lat, lon, offline)


@app.get("/api/all")
async def api_all(lat: float = Lat, lon: float = Lon, offline: bool = Offline):
    names = list(ADAPTERS)
    results = await asyncio.gather(*[ADAPTERS[n](lat, lon, offline) for n in names], return_exceptions=True)
    sources = {}
    for n, r in zip(names, results):
        if isinstance(r, Exception):  # adapters never raise, but be defensive
            r = {"source": n, "status": "error", "fetched_at": now_iso(), "units": {}, "data": None, "error": str(r)}
        sources[n] = r
    return {
        "lat": lat, "lon": lon, "generated_at": now_iso(),
        "status": {n: s["status"] for n, s in sources.items()},
        "sources": sources,
    }
