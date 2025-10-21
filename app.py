# Import all the necessary libraries
from flask import Flask, jsonify, request
from skyfield.api import load, wgs84
from datetime import datetime, timezone, timedelta
from flask_cors import CORS

# --- 1. Setup and Configuration ---

# Create an instance of the Flask application
app = Flask(__name__)
# This enables CORS and specifies that only requests from your website are allowed.
# Replace the placeholder URL with the actual URL of your tracker website.
app = Flask(__name__)
CORS(app, origins=[
    "http://127.0.0.1:5500",
    "https://your-tracker-site.tiiny.site"  # (optional, for when you go live)
])


# This sets up a loader that will download necessary data files from Skyfield
# and cache them in a new 'skyfield_data' folder in your project.
ts = load.timescale()
eph = load('de421.bsp')  # A standard file for planet positions

# The URL for the latest satellite orbital data (TLEs) from Celestrak
stations_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle'
satellites = load.tle_file(stations_url, reload=True) # reload=True ensures we get fresh data
iss = satellites[0] # The first satellite in the 'stations' group is always the ISS

# --- 2. API Routes ---

@app.route("/")
def home():
    """The home route to confirm the API is running."""
    return jsonify({
        "status": "online",
        "message": "Hooray! The ISS Spotter API server is working!"
    })

@app.route("/api/passes")
def get_iss_passes():
    """
    The main API endpoint to calculate visible ISS passes.
    It expects 'lat' and 'lon' as query parameters.
    Example: /api/passes?lat=19.0760&lon=72.8777
    """
    # Get latitude and longitude from the request URL's query parameters
    lat_str = request.args.get('lat')
    lon_str = request.args.get('lon')

    # --- Input Validation ---
    if not lat_str or not lon_str:
        return jsonify({"error": "Please provide 'lat' and 'lon' query parameters."}), 400
    try:
        latitude = float(lat_str)
        longitude = float(lon_str)
    except ValueError:
        return jsonify({"error": "Invalid latitude or longitude format."}), 400

    # --- Calculation ---
    observer_location = wgs84.latlon(latitude, longitude)
    t0 = ts.now()
    t1 = ts.utc(t0.utc.year, t0.utc.month, t0.utc.day + 10)
    times, events = iss.find_events(observer_location, t0, t1, altitude_degrees=10.0)

    passes = []
    event_names = {0: 'rise', 1: 'culminate', 2: 'set'}

    for t, event in zip(times, events):
        if event == 0:  # Start of a new pass (rise event)
            pass_details = {}  # Reset details for a new pass
            
            # --- THE DEFINITIVE FIX IS HERE ---
            # Correctly calculate the position for the rise event
            apparent = (iss - observer_location).at(t)
            alt, az, _ = apparent.altaz()
            
            pass_details['rise_time_utc'] = t.utc_datetime().isoformat()
            pass_details['rise_azimuth'] = round(az.degrees, 2)

        elif event == 1:  # Peak of the pass (culmination event)
            if 'rise_time_utc' in pass_details:
                apparent = (iss - observer_location).at(t)
                alt, az, _ = apparent.altaz()
                
                pass_details['max_elevation'] = round(alt.degrees, 2)
                pass_details['culminate_time_utc'] = t.utc_datetime().isoformat()

        elif event == 2:  # End of the pass (set event)
            if 'rise_time_utc' in pass_details:
                rise_dt = datetime.fromisoformat(pass_details['rise_time_utc'])
                set_dt = t.utc_datetime()
                duration = set_dt - rise_dt
                
                pass_details['duration_minutes'] = round(duration.total_seconds() / 60, 1)
                passes.append(pass_details)

    return jsonify(passes)

# --- 3. Run the Application ---

if __name__ == '__main__':
    app.run(debug=True)