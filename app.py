# Import all the necessary libraries
from flask import Flask, jsonify, request
from skyfield.api import load, wgs84, EarthSatellite
from datetime import datetime, timedelta
from flask_cors import CORS
from geopy.geocoders import Nominatim
import traceback
import geopandas as gpd
from shapely.geometry import Point
import pytz
import math
import os

# --- Get the absolute path of the directory where app.py is located ---
# This is your "API Folder"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Define the absolute paths to your shapefiles ---
SHAPEFILES_DIR = os.path.join(BASE_DIR, "Shapefiles")
TIMEZONES_DIR = os.path.join(SHAPEFILES_DIR, "Timezones")

# Paths to the specific files
STATE_SHP_PATH = os.path.join(SHAPEFILES_DIR, "ne_10m_admin_1_states_provinces.shp")
LAND_SHP_PATH = os.path.join(SHAPEFILES_DIR, "ne_10m_admin_0_countries.shp")
OCEAN_SHP_PATH = os.path.join(SHAPEFILES_DIR, "ne_10m_geography_marine_polys.shp")
TZ_SHP_PATH = os.path.join(TIMEZONES_DIR, "combined-shapefile-with-oceans.shp")

# --- 1. Setup and Configuration ---

app = Flask(__name__)
CORS(app, origins=[
    "http://127.0.0.1:5500",
    "https://isstracker.tiiny.site", # Replace with your front-end URL
    "http://localhost:8080",
]) 

# Load Skyfield data
ts = load.timescale()
eph = load('de421.bsp')
sun = eph['Sun']
earth = eph['Earth']

# --- Load all 3 High-Resolution (10m) Geospatial Data Files ---
try:
    print("Loading geospatial data...")
    # 1. States/Provinces (Most Detailed Land)
    STATE_DATA = gpd.read_file(STATE_SHP_PATH) 
    # 2. Countries (Broad Land Fallback)
    LAND_DATA = gpd.read_file(LAND_SHP_PATH)
    # 3. Oceans (Water)
    OCEAN_DATA = gpd.read_file(OCEAN_SHP_PATH)
    # 4. Timezones (Labels)
    TZ_DATA = gpd.read_file(TZ_SHP_PATH)
    print("Geospatial data loaded successfully.")

except Exception as e:
    print(f"CRITICAL ERROR: Could not load shapefiles. {e}")
    LAND_DATA = None
    OCEAN_DATA = None
    STATE_DATA = None
    TZ_DATA = None

    # --- GLOBAL VARIABLES FOR TLE CACHING (THE FIX) ---
ISS_SAT = None
LAST_TLE_FETCH = None

def load_initial_data():
    """Loads ISS data at startup so the first user doesn't wait."""
    global ISS_SAT, LAST_TLE_FETCH
    print("📥 Loading ISS Data at startup...")
    try:
        stations = load.tle_file(stations_url, reload=True)
        ISS_SAT = stations[0]
        LAST_TLE_FETCH = datetime.now()
        print("✅ ISS Data loaded successfully!")
    except Exception as e:
        print(f"⚠️ Error loading ISS data at startup: {e}")

# Load immediately on start
load_initial_data()

# Celestrak TLE URL
stations_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle'

# Geocoder setup (ONLY for /api/passes)
geolocator = Nominatim(user_agent="iss_tracker_api_v2")

# --- 2. Helper Functions (Unchanged) ---

def get_latest_iss():
    """
    SMART FUNCTION: Returns the ISS object from memory.
    Refreshes data from Celestrak ONLY if data is older than 60 minutes.
    This prevents the freezing and memory crashes.
    """
    global ISS_SAT, LAST_TLE_FETCH
    
    now = datetime.now()
    
    # Check if data is missing or old (> 1 hour)
    if ISS_SAT is None or LAST_TLE_FETCH is None or (now - LAST_TLE_FETCH).total_seconds() > 3600:
        print("🔄 TLE data is old. Fetching fresh data...")
        try:
            stations = load.tle_file(stations_url, reload=True)
            ISS_SAT = stations[0]
            LAST_TLE_FETCH = now
            print("✅ TLE Refreshed.")
        except Exception as e:
            print(f"⚠️ Failed to refresh TLE: {e}")
            # If refresh fails (e.g. Celestrak is down), keep using the old data so the app doesn't crash
            if ISS_SAT is None:
                raise e
                
    return ISS_SAT 

def get_lat_lon(location_name):
    """Geocodes a location name to latitude and longitude (for /api/passes)."""
    if not location_name or len(location_name.strip()) < 3:
        return None, None
    try:
        location = geolocator.geocode(location_name)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        print(f"Geocoder exception: {e}")
    return None, None

def is_pass_visible(iss, observer_location, start_time, end_time):
    """
    Checks if a pass is visible at any point between start and end time.
    """
    current_time = start_time
    while current_time < end_time:
        alt_sun, _, _ = (earth + observer_location).at(current_time).observe(sun).apparent().altaz()
        observer_in_darkness = alt_sun.degrees < -6
        iss_illuminated = iss.at(current_time).is_sunlit(eph)

        if observer_in_darkness and iss_illuminated:
            return True
        
        current_time = ts.utc(current_time.utc_datetime() + timedelta(seconds=30))
    return False

def get_timezone_name(lat, lon):
    """
    Finds the Timezone ID (e.g., 'Asia/Seoul') for a specific Lat/Lon
    using the loaded TZ_DATA shapefile.
    """
    if TZ_DATA is None:
        return "UTC" # Fallback if shapefiles failed
    
    try:
        p = Point(lon, lat)
        # Check which timezone polygon contains this point
        matches = TZ_DATA[TZ_DATA.geometry.contains(p)]
        if not matches.empty:
            return matches.iloc[0].get('tzid')
    except Exception as e:
        print(f"Timezone lookup error: {e}")
    
    return "UTC" # Default fallback

# --- 3. API Routes ---

@app.route("/")
def home():
    """The home route to confirm the API is running."""
    return jsonify({
        "status": "online",
        "message": "The ISS Spotter API server is working!"
    })


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

# --- 1. REBUILT TIMEZONE LOGIC (USING GEOPANDAS) ---
    tz_name = None
    local_time_str = "N/A"

    if TZ_DATA is not None:
        try:
            # Query the new GeoDataFrame
            matches = TZ_DATA[TZ_DATA.geometry.contains(iss_point)]
            if not matches.empty:
                # The column name in this shapefile is 'tzid'
                tz_name = matches.iloc[0].get('tzid') 
        except Exception as e:
            print(f"Error during TZ_DATA query: {e}")
            tz_name = "Error"
    
    if tz_name and tz_name != "Error":
        try:
            now_utc = ts.now()
            tz = pytz.timezone(tz_name) 
            now_in_tz = now_utc.astimezone(tz)
            local_time_str = now_in_tz.strftime('%H:%M:%S')
        except Exception as e:
            print(f"Timezone conversion failed: {e}")
            tz_name = "Error"
    # This handles oceans, which have no 'tzid'
    elif not tz_name: 
        tz_name = "N/A (Ocean)"
    # --- END REBUILT TIMEZONE LOGIC ---


    # --- 2. GEOLOCATION LOGIC (100% LOCAL) ---
    try:
        # Check States/Provinces First (Most Specific Land)
        if STATE_DATA is not None:
            # FIX: Check against the original geometry, not a buffer
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

        # Check Countries Second
        if LAND_DATA is not None:
            # FIX: Check against the original geometry
            matches = LAND_DATA[LAND_DATA.geometry.contains(iss_point)]
            if not matches.empty:
                country_name = matches.iloc[0].get('ADMIN') # FIX: Correct column name
                return jsonify({
                    "country": country_name,
                    "nearest": country_name,
                    "timezone": tz_name,
                    "local_time": local_time_str
                })
        
        # Check Oceans Third
        if OCEAN_DATA is not None:
            matches = OCEAN_DATA[OCEAN_DATA.geometry.contains(iss_point)]
            if not matches.empty:
                ocean_name = matches.iloc[0].get('name')
                return jsonify({
                    "country": "Over Water",
                    "nearest": ocean_name,
                    "timezone": "N/A (Ocean)",
                    "local_time": "N/A"
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


@app.route("/api/passes")
def get_iss_passes():
    # --- (Your existing /api/passes function) ---
    lat_str = request.args.get('lat')
    lon_str = request.args.get('lon')
    location_name = request.args.get('location')

    if (not lat_str or not lon_str) and location_name:
        lat, lon = get_lat_lon(location_name)
        if lat is None or lon is None:
            return jsonify({"error": "Location not found or invalid location"}), 404
    else:
        lat = lat_str
        lon = lon_str

    if lat is None or lon is None:
        return jsonify({"error": "Please provide 'lat' and 'lon' or a valid location name."}), 400

    try:
        latitude = float(lat)
        longitude = float(lon)
    except ValueError:
        return jsonify({"error": "Invalid latitude or longitude format."}), 400
    target_tz = get_timezone_name(latitude, longitude)

    try:
        iss = get_latest_iss()
        observer_location = wgs84.latlon(latitude, longitude)
        t0 = ts.now()
        t1 = t0 + timedelta(days=5)

        times, events = iss.find_events(observer_location, t0, t1, altitude_degrees=10.0)

        passes = []
        rise_time, max_time, set_time = None, None, None

        for t, event in zip(times, events):
            if event == 0:  # Rise
                rise_time = t
            elif event == 1: # Culminate (max elevation)
                max_time = t
            elif event == 2: # Set
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

        return jsonify(passes)
        
    except Exception as e:
        print(f"An error occurred processing /api/passes:")
        print(traceback.format_exc())
        return jsonify({"error": "An internal server error occurred."}), 500
    
@app.route("/api/telemetry")
def get_telemetry():
    """
    Calculates real-time ISS telemetry (Position, Speed, Altitude, etc.)
    Replaces the 'wheretheiss.at' API.
    """
    try:
        iss = get_latest_iss()
        t = ts.now()
        
        # 1. Calculate Position (Geocentric)
        geocentric = iss.at(t)
        subpoint = geocentric.subpoint()
        
        latitude = subpoint.latitude.degrees
        longitude = subpoint.longitude.degrees
        altitude_km = subpoint.elevation.km
        
        # 2. Calculate Velocity (Speed)
        # Skyfield gives velocity in km/s as a vector (x, y, z)
        velocity_vector = geocentric.velocity.km_per_s
        # Speed = sqrt(x^2 + y^2 + z^2)
        speed_km_s = math.sqrt(sum(v**2 for v in velocity_vector))
        speed_km_h = speed_km_s * 3600
        
        # 3. Calculate Visibility (Daylight vs Eclipsed)
        is_sunlit = iss.at(t).is_sunlit(eph)
        visibility_status = "daylight" if is_sunlit else "eclipsed"
        
        # 4. Calculate Footprint (Horizon)
        earth_radius_km = 6371.0
        # Horizon angle (theta)
        theta = math.acos(earth_radius_km / (earth_radius_km + altitude_km))
        # Arc distance (radius of footprint on surface)
        footprint_radius_km = theta * earth_radius_km
        # Diameter (to match old API format approx)
        footprint_diameter_km = footprint_radius_km * 2
        
        return jsonify({
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude_km,
            "velocity": speed_km_h,
            "visibility": visibility_status,
            "footprint": footprint_diameter_km,
            "timestamp": t.utc_datetime().timestamp()
        })

    except Exception as e:
        print(f"Telemetry Error: {e}")
        return jsonify({"error": "Could not calculate telemetry"}), 500        

# --- 4. Run the Application ---

if __name__ == '__main__':
    app.run(debug=False)