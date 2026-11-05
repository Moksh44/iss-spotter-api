---
title: ISS Tracker API
emoji: 🚀
colorFrom: blue
colorTo: gray
sdk: docker
pinned: false
app_port: 7860
---

# ISS Spotter API

Flask backend for the [ISS Tracker](https://github.com/Moksh44/ISS-Tracker). It calculates live International Space Station telemetry, resolves the ISS's current geographic location from local shapefiles, and predicts visible passes for a requested location.

**Live API:** [mokshi85-iss-tracker-api.hf.space](https://mokshi85-iss-tracker-api.hf.space)<br>
**Frontend:** [Moksh44/ISS-Tracker](https://github.com/Moksh44/ISS-Tracker)

## What it provides

- ISS latitude, longitude, altitude, velocity, footprint, and solar visibility
- Celestial coordinates and constellation
- Estimated orbital period and orbits per day
- Country, state/ocean, local time, and time-zone lookup
- Geocoding of place names through Nominatim
- Visible ISS passes over the next seven days
- Cached TLE downloads refreshed every 12 hours
- Docker/Gunicorn deployment on port `7860`

## API reference

### `GET /`

Health check.

```json
{
  "status": "online",
  "message": "The ISS Spotter API server is working!"
}
```

### `GET /api/telemetry`

Returns calculated telemetry for the ISS. No query parameters are required.

Example response:

```json
{
  "name": "iss",
  "id": 25544,
  "latitude": 12.34,
  "longitude": -56.78,
  "altitude": 408.1,
  "velocity": 27580.4,
  "visibility": "Visible",
  "footprint": 4435.2,
  "timestamp": 1730000000.0,
  "units": "km",
  "ra": 10.2,
  "dec": -4.1,
  "constellation": "Leo",
  "orbit_period": 92.7,
  "orbits_per_day": 15.5
}
```

`velocity` is in km/h, `altitude` and `footprint` are in km, right ascension is in decimal hours, and declination is in decimal degrees.

### `GET /api/location`

Resolves the ISS's current coordinates to a country/state, ocean, local time, and time zone.

| Parameter | Required | Description |
|---|---:|---|
| `lat` | Yes | Latitude in decimal degrees |
| `lon` | Yes | Longitude in decimal degrees |

Example:

```bash
curl "https://mokshi85-iss-tracker-api.hf.space/api/location?lat=28.61&lon=77.21"
```

Example response:

```json
{
  "country": "India",
  "nearest": "Delhi",
  "timezone": "Asia/Kolkata",
  "local_time": "18:42:10"
}
```

### `GET /api/passes`

Returns visible ISS passes during the next seven days. A pass must rise above 10° elevation and occur while the observer is in darkness and the ISS is sunlit.

Use either coordinates or a place name:

```bash
curl "https://mokshi85-iss-tracker-api.hf.space/api/passes?lat=28.61&lon=77.21"
curl "https://mokshi85-iss-tracker-api.hf.space/api/passes?location=New%20Delhi"
```

| Parameter | Required | Description |
|---|---:|---|
| `lat` and `lon` | One option | Observer coordinates in decimal degrees |
| `location` | One option | Place name geocoded with Nominatim |

Each pass includes UTC rise, maximum, and set timestamps; rise/set azimuth; maximum elevation and azimuth; duration; and the resolved time-zone identifier. Place-name searches also return `location_label`.

## Run locally

### Requirements

- Python 3.11+
- The geospatial shapefiles in `Shapefiles/`
- The `de421.bsp` ephemeris file
- Network access for TLE downloads and place-name geocoding

Create an environment and install dependencies:

```bash
git clone https://github.com/Moksh44/iss-spotter-api.git
cd iss-spotter-api
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

Start the development server:

```bash
python app.py
```

The API is available at [http://127.0.0.1:5000](http://127.0.0.1:5000).

For a production-style local run:

```bash
gunicorn --bind 0.0.0.0:7860 app:app
```

## Docker

Build and run the image:

```bash
docker build -t iss-spotter-api .
docker run --rm -p 7860:7860 iss-spotter-api
```

The health endpoint is then available at [http://127.0.0.1:7860](http://127.0.0.1:7860).

## Configuration

Allowed browser origins are defined in `ALLOWED_ORIGINS` in [`app.py`](./app.py). Add the origin of any local or deployed frontend there before making browser requests from it.

The API downloads ISS TLE data from [Where The ISS At](https://wheretheiss.at/) and caches it in `stations.txt` for up to 12 hours. The first request that needs orbital data may therefore take longer than subsequent requests.

## Data files

- `de421.bsp` — Skyfield ephemeris data
- `Shapefiles/` — Natural Earth country, state/province, ocean, and time-zone data used for local lookups
- `stations.txt` — generated TLE cache; it is not required in the repository

The repository uses Git LFS for large shapefile components. Ensure Git LFS is installed and the LFS objects are available when cloning or deploying the project.

## Architecture

```text
Frontend
   |
   +-- /api/telemetry  -> Skyfield + cached ISS TLE
   +-- /api/location   -> GeoPandas point-in-polygon lookups
   +-- /api/passes     -> Skyfield event/visibility calculations
                              |
                              +-- Nominatim for place-name geocoding
```

## Operational notes

- TLE data changes over time, so telemetry and pass results are time-sensitive.
- Nominatim is a public service; use a descriptive user agent and avoid excessive request rates.
- The API returns JSON errors with HTTP `400`, `403`, `404`, or `500` status codes for invalid input, disallowed origins, missing locations, and server failures.
- Geospatial files are loaded when the application starts. Missing or invalid files reduce location accuracy and can trigger fallback responses.

## License

No license has been specified yet. Until a license is added to the repository, all rights are reserved by the copyright holder.