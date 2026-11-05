# Monsoon Path – Flood-aware walking route assistant

A Flask web-app prototype based on the Monsoon Path mini-project presentation.

## Features

- User registration, login and logout
- Flood reports with photo, GPS coordinates, water depth and description
- Admin approval/rejection of flood reports
- OpenStreetMap pedestrian network retrieval using OSMnx
- Open-Meteo current precipitation lookup (or manually supplied rainfall)
- Demonstration road-segment risk scoring
- NetworkX route calculation that excludes high-risk segments
- Leaflet map with route segments and approved flood-report markers
- Distance, estimated walking time and no-safe-route warning

## Requirements

- Python 3.10 or newer
- Internet connection (OpenStreetMap, Open-Meteo, Nominatim and Leaflet tiles)
- Windows, macOS or Linux

## Run on Windows

Open Command Prompt in this folder:

```bash
py -m venv venv
venv\\Scripts\\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Run on macOS/Linux

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## First-time demo

1. Register a user account.
2. Log in.
3. Enter a start and destination, for example two nearby places in Mangaluru.
4. Leave rainfall blank to try Open-Meteo, or enter a test value such as `15`.
5. Submit a flood report using GPS or manually entered coordinates.
6. Open `/admin` and sign in with the development password `monsoon-admin`.
7. Approve the report. Run route planning again to include it in the risk calculation.

## Configuration

Set environment variables before running:

- `SECRET_KEY`: long random Flask session secret
- `ADMIN_PASSWORD`: admin moderation password
- `DEM_PATH`: absolute path to a local DEM GeoTIFF (optional)

The defaults are for local development only. Do not deploy with the defaults.

## How the prototype risk engine works

For each road edge, it computes a heuristic score:

- Rainfall contribution: up to 0.45, increasing with rainfall
- Low-elevation contribution: up to 0.30, only when node elevation attributes are available
- Approved flood report nearby: 0.45 when a report is within 100 metres

Risk levels:

- Low: score below 0.30
- Medium: 0.30 to below 0.67
- High: 0.67 or above

High-risk edges are removed from the graph. NetworkX finds a route over the remaining graph, with medium-risk edges penalised. If no path remains, the app shows a no-safe-route warning.

## Important limitations

This is an academic prototype, not a validated flood forecasting or emergency navigation system.

- The app can now read a local georeferenced DEM GeoTIFF when `DEM_PATH` is configured. It samples raster elevations at OSM road-graph nodes and uses those elevations in the relative-terrain risk component. Without a configured DEM, terrain contributes zero. Obtain a DEM GeoTIFF covering the demo area from a legitimate source such as NASA SRTM or Copernicus DEM, check its licence and resolution, and set `DEM_PATH` to its full path. This is a raster integration point, not an automatic DEM downloader.
- The rainfall input is current precipitation in mm, not a calibrated flood-depth forecast. For better results, use a rainfall accumulation/time window and a locally validated risk formula.
- Flood reports are user-generated and must be reviewed. Admin approval is a simple demo moderation mechanism.
- OSM and geocoding services have usage policies and rate limits. Avoid repeated rapid requests.
- A route is based on mapped footways and may not reflect temporary closures, stairs, private access or actual on-ground conditions.
- The route line joins road-network nodes; it is a prototype display rather than turn-by-turn navigation.
- For production, add CSRF protection, stronger admin authentication, image validation/scanning, rate limiting, privacy controls and HTTPS.

## Suggested next improvements

1. Add SRTM/DEM raster processing with `osmnx.elevation.add_node_elevations_raster`.
2. Use time-window rainfall forecasts and a locally calibrated risk formula.
3. Add report expiry and duplicate-report handling.
4. Add turn-by-turn instructions and voice guidance.
5. Add regional-language and offline-map support.


## Optional SRTM / DEM setup (terrain-risk integration)

1. Obtain a DEM GeoTIFF covering the area you want to demonstrate (for example, the Mangaluru region). Ensure the file has a valid CRS and elevation values in metres.
2. Install the added dependencies with `pip install -r requirements.txt`.
3. Set the environment variable before starting Flask in Windows Command Prompt:

```bat
set DEM_PATH=C:\path\to\your\mangaluru_dem.tif
python app.py
```

4. Run a route. The result panel reports how many road-network nodes received elevation samples.

If no DEM is configured, the app continues to work and explicitly reports that DEM is not configured. DEM coverage, vertical units, nodata values and raster resolution affect results. The relative-elevation score is a simple prototype heuristic, not hydrological modelling.
