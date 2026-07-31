# Import libraries
from flask import Flask, jsonify, request
# flask - Flask Framework, jsonify - Converts Py to JSON
from skyfield.api import load, wgs84, load_constellation_map, load_constellation_names
# Skyfiled library, wgs84 - Formula Model
from datetime import timedelta, datetime
# datetime - dates and time
from flask_cors import CORS
# flask_cors - CORS Gateway framework
from geopy.geocoders import Nominatim
# geopy - library to access geocoding services, nominatim - openstreetMap's geocoding service
import traceback
# traceback - Library to handle exceptional fallbacks
import geopandas as gpd
# geopandas - manages geospatial data
import numpy as np
# numpy - manages vector, matrice and multi dimensional array calculations
from shapely.geometry import Point
# Engine to handle 2D geometry
import pytz
# Python time zone library to handle global and local time offsets
import math
# library to handle basic math operations
import os


# acess to local files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# paths to shapefiles
SHAPEFILES_DIR = os.path.join(BASE_DIR, "Shapefiles")
TIMEZONES_DIR = os.path.join(SHAPEFILES_DIR, "Timezones")
STATE_SHP_PATH = os.path.join(SHAPEFILES_DIR, "ne_10m_admin_1_states_provinces.shp")
LAND_SHP_PATH = os.path.join(SHAPEFILES_DIR, "ne_10m_admin_0_countries.shp")
OCEAN_SHP_PATH = os.path.join(SHAPEFILES_DIR, "ne_10m_geography_marine_polys.shp")
TZ_SHP_PATH = os.path.join(TIMEZONES_DIR, "combined-shapefile-with-oceans.shp")

# Setup and Configuration
app = Flask(__name__)
CORS(app, origins=[
    "http://127.0.0.1:5500",
    "https://.tiiny.site",
]) 

# Load Skyfield Data
ts = load.timescale()
eph = load('de421.bsp')
sun = eph['Sun']
earth = eph['Earth']

# DEFINE THE URL
stations_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle'

# Global variables for caching
cached_iss = None
last_tle_update = None

# Fetch and cache the orbital Data
def get_iss():
    global cached_iss, last_tle_update
    now = datetime.now()

    if cached_iss is None or last_tle_update is None or (now - last_tle_update).total_seconds() > 43200:
        try:
            tles = load.tle_file(stations_url, reload=True)
            if not tles:
                raise RuntimeError("TLE file downloaded but contained no satellites.")
            by_name = {tle.name: tle for tle in tles}
            cached_iss = by_name.get('ISS (ZARYA)', tles[0]) 
            last_tle_update = now
        except Exception as e:
            print(f"Failed to fetch TLE: {e}")
            if cached_iss is None:
                raise

    return cached_iss
try:
    lookup_constellation = load_constellation_map()
    constellation_names_dict = dict(load_constellation_names())
    print("Constellation Data Loaded.")
except Exception as e:
    print(f"Warning: Could not load constellation data: {e}")
    lookup_constellation = None
    constellation_names_dict = {}

# Load all 3 High-Resolution Geospatial Data Files
try:
    # 1. States/Provinces
    STATE_DATA = gpd.read_file(STATE_SHP_PATH) 
    # 2. Countries
    LAND_DATA = gpd.read_file(LAND_SHP_PATH)
    # 3. Oceans
    OCEAN_DATA = gpd.read_file(OCEAN_SHP_PATH)
    # 4. Timezones
    TZ_DATA = gpd.read_file(TZ_SHP_PATH)

except Exception as e:
    print(f"CRITICAL ERROR: Could not load shapefiles. {e}")
    LAND_DATA = None
    OCEAN_DATA = None
    STATE_DATA = None
    TZ_DATA = None

# Geocoder setup
geolocator = Nominatim(user_agent="iss_tracker_api_v2")

# Helper Function for Geocoder
def get_lat_lon(location_name):
    """Geocodes a location name to latitude, longitude, and a display label."""
    if not location_name or len(location_name.strip()) < 3:
        return None, None, None
    try:
        location = geolocator.geocode(location_name, language='en')
        if location:
            raw_parts = [p.strip() for p in location.address.split(',')]
            clean_parts = []
            seen = set()
            for p in raw_parts:
                if p not in seen and not p.isdigit():
                    seen.add(p)
                    clean_parts.append(p)
            if len(clean_parts) >= 3:
                label = f"{clean_parts[0]}, {clean_parts[-2]}, {clean_parts[-1]}"
            else:
                label = ', '.join(clean_parts)
            return location.latitude, location.longitude, label
    except Exception as e:
        print(f"Geocoder exception: {e}")
    return None, None, None

#Function to find visibility sighitings
def is_pass_visible(iss, observer_location, start_time, end_time):
    """
    Checks if a pass is visible at any point between start and end time.
    """
    current_time = start_time
    max_iterations = 100
    iteration = 0
    while current_time < end_time and iteration < max_iterations:
        alt_sun, _, _ = (earth + observer_location).at(current_time).observe(sun).apparent().altaz()
        observer_in_darkness = alt_sun.degrees < -6
        iss_illuminated = iss.at(current_time).is_sunlit(eph)

        if observer_in_darkness and iss_illuminated:
            return True
        
        current_time = ts.utc(current_time.utc_datetime() + timedelta(seconds=60))
        iteration += 1
    return False

# Function to calculate timezone
def get_timezone_name(lat, lon):
    """
    Finds the Timezone ID for a specific Lat/Lon using the loaded TZ_DATA shapefile.
    """
    if TZ_DATA is None:
        return "Data Error"
    try:
        p = Point(lon, lat)
        matches = TZ_DATA[TZ_DATA.geometry.contains(p)]
        if not matches.empty:
            return matches.iloc[0].get('tzid') or "UTC"
    except Exception as e:
        print(f"Timezone lookup error: {e}")
    return "UTC"

# API Routes
@app.route("/")
def home():
    """The home route to confirm that API is running."""
    return jsonify({
        "status": "online",
        "message": "The ISS Spotter API server is working!"
    })

# API route for location
@app.route("/api/location")
def get_iss_location():
    """
    Takes ISS coordinates (lat/lon) and returns the Ocean, Country, or State name
    AND the local time zone, using 100% local data.
    """
    lat_str = request.args.get('lat')
    lon_str = request.args.get('lon')

    try:
        latitude = float(lat_str)
        longitude = float(lon_str)
        iss_point = Point(longitude, latitude) 
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid or missing latitude/longitude."}), 400

    # REBUILT TIMEZONE LOGIC (USING GEOPANDAS)
    tz_name = get_timezone_name(latitude, longitude)
    local_time_str = "N/A"

    if tz_name not in ["Data Error", "UTC"]:
        try:
            now_utc = datetime.now(pytz.utc)
            tz = pytz.timezone(tz_name)
            now_in_tz = now_utc.astimezone(tz)
            local_time_str = now_in_tz.strftime('%H:%M:%S')
        except Exception as e:
            print(f"Timezone conversion failed: {e}")
    if tz_name =="UTC":
        tz_name = "N/A (Ocean)"
    elif tz_name == "Data Error":
        tz_name = "UTC (Fallback)"

    # Geolocation Time Zone Check
    try:
        if STATE_DATA is not None:
            matches = STATE_DATA[STATE_DATA.geometry.contains(iss_point)]
            if not matches.empty:
                state_name = matches.iloc[0].get('name')
                country_name = matches.iloc[0].get('admin') 
                return jsonify({
                    "country": country_name,
                    "nearest": state_name,
                    "timezone": tz_name,
                    "local_time": local_time_str
                })
            
        # Check Countries
        if LAND_DATA is not None:
            matches = LAND_DATA[LAND_DATA.geometry.contains(iss_point)]
            if not matches.empty:
                country_name = matches.iloc[0].get('ADMIN')
                return jsonify({
                    "country": country_name,
                    "nearest": country_name,
                    "timezone": tz_name,
                    "local_time": local_time_str
                })
        
        # Check Oceans
        if OCEAN_DATA is not None:
            matches = OCEAN_DATA[OCEAN_DATA.geometry.contains(iss_point)]
            if not matches.empty:
                ocean_name = matches.iloc[0].get('name')
                return jsonify({
                    "country": "Over Water",
                    "nearest": ocean_name,
                    "timezone": tz_name,
                    "local_time": local_time_str
                })
        
        # Check for Antarctica
        if latitude < -60:
             return jsonify({
                 "country": "Antarctica", 
                 "nearest": "Antarctica",
                 "timezone": tz_name,
                 "local_time": local_time_str
            })

        # Final Fallback
        return jsonify({
            "country": "Unknown", 
            "nearest": "Unknown Location",
            "timezone": "Unknown",
            "local_time": "N/A"
        })

    except Exception as e:
        print(f"Error in /api/location: {traceback.format_exc()}")
        return jsonify({"error": "An internal server error occurred."}), 500


# API route for sighitings
@app.route("/api/passes")
def get_iss_passes():
    lat_str = request.args.get('lat')
    lon_str = request.args.get('lon')
    location_name = request.args.get('location')

    resolved_label = None
    
    if (not lat_str or not lon_str) and location_name:
        lat, lon, resolved_label = get_lat_lon(location_name)
        if lat is None or lon is None:
            return jsonify({"error": "Location not found or invalid location"}), 404
    else:
        lat = lat_str
        lon = lon_str
        resolved_label = None

    if lat is None or lon is None:
        return jsonify({"error": "Please provide 'lat' and 'lon' or a valid location name."}), 400

    try:
        latitude = float(lat)
        longitude = float(lon)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid latitude or longitude format."}), 400
    target_tz = get_timezone_name(latitude, longitude)

    try:
        iss = get_iss()
        observer_location = wgs84.latlon(latitude, longitude)
        t0 = ts.now()
        t1 = ts.tt_jd(t0.tt + 7.0)

        times, events = iss.find_events(observer_location, t0, t1, altitude_degrees=10.0)

        passes = []
        rise_time, max_time, set_time = None, None, None

        for t, event in zip(times, events):
            if event == 0:
                rise_time = t
            elif event == 1:
                max_time = t
            elif event == 2:
                set_time = t

            if rise_time is not None and max_time is not None and set_time is not None:
                if is_pass_visible(iss, observer_location, rise_time, set_time):
                    
                    rise_apparent = (iss - observer_location).at(rise_time)
                    _, rise_az, _ = rise_apparent.altaz()
                    
                    max_apparent = (iss - observer_location).at(max_time)
                    max_alt, max_az, _ = max_apparent.altaz()
                    
                    set_apparent = (iss - observer_location).at(set_time)
                    _, set_az, _ = set_apparent.altaz()
                    
                    duration = (set_time - rise_time) * 24 * 60
                    
                    passes.append({
                        'rise_time_utc': rise_time.utc_datetime().isoformat(),
                        'rise_azimuth': round(rise_az.degrees, 2),
                        'max_time_utc': max_time.utc_datetime().isoformat(),
                        'max_elevation': round(max_alt.degrees, 2),
                        'max_azimuth': round(max_az.degrees, 2),
                        'set_time_utc': set_time.utc_datetime().isoformat(),
                        'set_azimuth': round(set_az.degrees, 2),
                        'duration_minutes': round(duration, 1),
                        'timezone_id': target_tz
                    })
                
                rise_time, max_time, set_time = None, None, None

        return jsonify({
            "passes":passes,
            "location_label": resolved_label
        })
        
    except Exception as e:
        print(f"An error occurred processing /api/passes:")
        print(traceback.format_exc())
        return jsonify({"error": "An internal server error occurred."}), 500

# API Route for Telemetry Data
@app.route("/api/telemetry")
def get_telemetry():
    """
    Calculates real-time ISS position, velocity, and visibility footprint.
    Replaces the external 'wheretheiss.at' API.
    """
    try:
        # Get the ISS object
        iss = get_iss()
        
        # Calculate Live position
        t = ts.now()
        geocentric = iss.at(t)
        subpoint = wgs84.subpoint(geocentric)
        
        # Extract Core Data
        latitude = subpoint.latitude.degrees
        longitude = subpoint.longitude.degrees
        altitude_km = subpoint.elevation.km
        
        # Calculate Velocity (Speed)
        velocity_vector = geocentric.velocity.km_per_s
        speed_km_s = float(np.linalg.norm(velocity_vector))
        velocity_km_h = speed_km_s * 3600
        
        # Calculate Footprint (Visibility Diameter in km)
        R = 6371.0
        if altitude_km > 0:
            angle = math.acos(R / (R + altitude_km))
            footprint_diameter_km = 2 * (R * angle)
        else:
            footprint_diameter_km = 0

        # Solar Visibility (Day/Night)
        is_sunlit = iss.at(t).is_sunlit(eph)
        visibility_status = "Visible" if is_sunlit else "Invisible"

        # ASTRONOMY CALCULATIONS (RA/Dec & Constellation)
        ra, dec, distance = geocentric.radec()
        
        constellation_full_name = "Unknown"
        if lookup_constellation:
            abbrev = lookup_constellation(geocentric)
            constellation_full_name = constellation_names_dict.get(abbrev, abbrev)
        
        ra_hours = ra.hours
        dec_degrees = dec.degrees

        # LIVE ORBIT PERIOD CALCULATION
        mean_motion_rad_min = iss.model.no_kozai
        orbit_period_mins = (2 * math.pi) / mean_motion_rad_min
        
        # Calculate orbits per day
        orbits_per_day = 1440 / orbit_period_mins

        return jsonify({
            "name": "iss",
            "id": 25544,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude_km,
            "velocity": velocity_km_h,
            "visibility": visibility_status,
            "footprint": footprint_diameter_km,
            "timestamp": t.utc_datetime().timestamp(),
            "units": "km",
            "ra": ra_hours,
            "dec": dec_degrees,
            "constellation": constellation_full_name,
            "orbit_period": orbit_period_mins,
            "orbits_per_day": orbits_per_day
        })

    except Exception as e:
        print(f"Telemetry Error: {traceback.format_exc()}")
        return jsonify({"error": "Failed to calculate telemetry"}), 500         

# Run the Application
if __name__ == '__main__':
    app.run(debug=False)