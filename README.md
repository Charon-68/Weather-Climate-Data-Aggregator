# Open Weather & Climate Aggregator (prototype)

A small local web portal that gathers **four weather and climate data streams** for any location you pick. It uses only free, keyless, open data sources:

| Stream | What you see |
|---|---|
| **Ground observations** | Latest METAR from the nearest airport station: temperature, dew point, RH, wind, visibility, QNH, weather, plus a 24 h temperature series |
| **NWP forecast** | 7-day daily max/min temperature and precipitation, plus hourly 2 m temperature from **GFS vs ECMWF IFS vs ICON** side by side |
| **Climatology** | NASA POWER monthly normals (2001–2025): temperature and precipitation, **solar irradiance and 10 m wind** (renewable-energy resource), with the current month highlighted and "this month normally" vs the 7-day forecast |
| **Satellite** | NASA GIBS tiles on the map: VIIRS NOAA-20 true color (daily), **GPM IMERG** precipitation rate, Himawari-9 IR Band 13 (10-min) |

## Run

```bash
cd weather-aggregator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Then open http://localhost:8000. Interactive API docs (Swagger) are at http://localhost:8000/docs.

## Deploy (Render, free tier)

The repo includes a `render.yaml`, so Render can set up the service from it.

1. Sign in at https://render.com with GitHub.
2. Click **New → Blueprint** and pick this repository. Render reads `render.yaml`.
3. Click **Apply** and wait for the build (about 2–3 minutes). The app goes live at `https://weather-climate-aggregator.onrender.com` (or a similar URL).

To set it up by hand instead, choose **New → Web Service**. Use the build command `pip install -r requirements.txt` and the start command `uvicorn app:app --host 0.0.0.0 --port $PORT`.

Free instances go to sleep after 15 minutes without traffic, and the first request then takes about 50 seconds. Open the URL a few minutes before a demo.

## Architecture

```
Sources (free, keyless)          Adapters (sources/*.py)             Cache                     API (app.py)        UI
aviationweather.gov METAR  ─┐    async fetch(lat, lon) ->           in-memory TTL 10 min      /api/geocode        static/index.html
Open-Meteo NWP (3 models)  ─┼─►  normalized envelope           ─►   + disk cache/*.json   ─►  /api/forecast   ─►  Leaflet map
NASA POWER climatology     ─┘    {source, status, fetched_at,       live fails -> disk copy   /api/climatology    + 4 stream cards
                                  units, data, error}                status = "cached"         /api/observations   + status badges
NASA GIBS WMTS tiles  ───────────────────────────────────────────────────────────────────────  (browser direct) ─►  map layers
```

- **One adapter per source** (`sources/forecast.py`, `climatology.py`, `observations.py`, `geocode.py`). Each one returns the same normalized envelope, so adding a new source (for example ERA5 or IMD) means writing one new module.
- **`/api/all`** runs every adapter in parallel (`asyncio.gather`) and returns the combined JSON with a status for each source.
- **Fault isolation:** every adapter catches all exceptions. If one source fails, only its own card shows *unavailable*.
- **Offline fallback:** every successful response is written to `cache/{source}_{lat:.2f}_{lon:.2f}.json`. If a later live fetch fails, the app serves the disk copy with status `cached`. The cache is pre-warmed for IIT Bombay and Delhi. To demo this, tick **"Simulate source outage"** in the header, or call any endpoint with `&offline=true`.
- Times are shown in IST, and every chart axis is labelled with its units.

## Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/geocode?q=Mumbai` | Place search (Open-Meteo geocoding) |
| `GET /api/forecast?lat=&lon=` | NWP forecast + multi-model comparison |
| `GET /api/climatology?lat=&lon=` | NASA POWER monthly normals |
| `GET /api/observations?lat=&lon=` | Nearest METAR station, latest obs and 24 h series |
| `GET /api/all?lat=&lon=` | All of the above in parallel, with a status per source |

Each lat/lon endpoint accepts `&offline=true`, which simulates an outage by skipping the live fetch and serving the cache.

## Data sources

| Source | Provider | Update frequency / latency | Format | License |
|---|---|---|---|---|
| METAR surface observations | NOAA Aviation Weather Center data API (reports from IMD airport met offices) | 30–60 min, minutes latency | JSON | US Gov, public domain |
| NWP forecast | Open-Meteo: best-match blend, NOAA GFS, ECMWF IFS 0.25°, DWD ICON | Model runs every 3–12 h, 7-day horizon | JSON | CC BY 4.0 |
| Climatology | NASA POWER Climatology API (MERRA-2 + CERES SYN1deg), 2001–2025 | Static long-term means | JSON | NASA open data |
| Satellite | NASA GIBS WMTS (EPSG:3857) | VIIRS daily (~3 h NRT), IMERG daily (~1–2 d lag), Himawari 10 min | JPEG/PNG tiles | NASA open data |
| Geocoding | Open-Meteo Geocoding (GeoNames) | On demand | JSON | CC BY 4.0 |
| Base map / labels | OpenStreetMap; Esri World Boundaries & Places | Continuous | PNG tiles | ODbL; Esri attribution |

### Implementation notes (verified while building)
- The METAR `bbox` order is `minLat,minLon,maxLat,maxLon` (±1.5° box). If the box query fails, the adapter falls back to a built-in list of major Indian airports. If no station is within 250 km (for example over the ocean), the card shows *unavailable*.
- Open-Meteo multi-model responses add the model name to each variable (`temperature_2m_ecmwf_ifs025`). All three models currently work; if one starts failing, the adapter drops it and keeps the others.
- **VIIRS SNPP true color in GIBS stops at 2026-11-02**, so the base layer uses **VIIRS NOAA-20** (same instrument type). The daily IMERG layer lags about 2 days, so the UI automatically uses the latest available date.
- CARTO label tiles now require an API key, so labels come from Esri's keyless reference layer.

## Next steps for the 2-month project

1. **ERA5 reanalysis** via the Copernicus CDS API (`cdsapi`): hourly history and proper 1991–2020 normals.
2. **IMD gridded rainfall and temperature** via `imdlib` (0.25° rainfall, 1° temperature) as the authoritative Indian climatology.
3. **INSAT-3D/3DR** imagery and products (cloud, OLR, rainfall) from **MOSDAC**.
4. **Ground networks:** IMD AWS/ARG ingestion, plus ingestion from our own IoT stations through a simple push API.
5. **Gridded formats:** NetCDF/GRIB handling with `xarray` + `cfgrib` + `dask`, served as point and area time series.
6. **Analytics:** anomalies against 1991–2020 normals, heat-stress indices (heat index, WBGT), and a solar/wind resource panel (GHI, PV yield, wind power density at hub height).
7. **Validation:** forecast verification against observations (bias and RMSE per model), which builds on the model-comparison chart.
8. **Platform:** a persistent store (PostGIS/TimescaleDB), scheduled ingestion jobs, a public API with rate limits, Docker deployment, and an open-source license and contribution guide.
