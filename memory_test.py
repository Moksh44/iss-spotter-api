import time
import os
import psutil
import geopandas as gpd

# Function to get current memory usage in MB
def get_memory_usage():
    process = psutil.Process(os.getpid())
    bytes_usage = process.memory_info().rss
    return bytes_usage / 1024 / 1024  # Convert to MB

print(f"🔹 Baseline Memory (Empty Python): {get_memory_usage():.2f} MB")

# --- DEFINE PATHS (Matched exactly to your app.py) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHAPEFILES_DIR = os.path.join(BASE_DIR, "Shapefiles")
TIMEZONES_DIR = os.path.join(SHAPEFILES_DIR, "Timezones")

# 10m File Paths (The High-Res files you are using)
STATE_SHP_PATH = os.path.join(SHAPEFILES_DIR, "ne_10m_admin_1_states_provinces.shp")
LAND_SHP_PATH = os.path.join(SHAPEFILES_DIR, "ne_10m_admin_0_countries.shp")
OCEAN_SHP_PATH = os.path.join(SHAPEFILES_DIR, "ne_10m_geography_marine_polys.shp")
TZ_SHP_PATH = os.path.join(TIMEZONES_DIR, "combined-shapefile-with-oceans.shp")

print("\n🚀 Loading ALL Shapefiles... (Watch the memory spike!)")

try:
    # 1. Load States
    start_mem = get_memory_usage()
    print("   1. Loading States (10m)...", end=" ", flush=True)
    STATE_DATA = gpd.read_file(STATE_SHP_PATH)
    diff = get_memory_usage() - start_mem
    print(f"DONE. (+{diff:.2f} MB)")

    # 2. Load Countries
    start_mem = get_memory_usage()
    print("   2. Loading Countries (10m)...", end=" ", flush=True)
    LAND_DATA = gpd.read_file(LAND_SHP_PATH)
    diff = get_memory_usage() - start_mem
    print(f"DONE. (+{diff:.2f} MB)")

    # 3. Load Oceans
    start_mem = get_memory_usage()
    print("   3. Loading Oceans (10m)...", end=" ", flush=True)
    OCEAN_DATA = gpd.read_file(OCEAN_SHP_PATH)
    diff = get_memory_usage() - start_mem
    print(f"DONE. (+{diff:.2f} MB)")

    # 4. Load Timezones (The Suspected Giant)
    start_mem = get_memory_usage()
    print("   4. Loading Timezones (Huge)...", end=" ", flush=True)
    TZ_DATA = gpd.read_file(TZ_SHP_PATH)
    diff = get_memory_usage() - start_mem
    print(f"DONE. (+{diff:.2f} MB)")

    # --- FINAL REPORT ---
    total_mem = get_memory_usage()
    print("-" * 30)
    print(f"🛑 TOTAL MEMORY USED: {total_mem:.2f} MB")
    print(f"💾 Render Limit:      512.00 MB")
    
    if total_mem > 400:
        print("\n⚠️  DANGER: You are dangerously close to the limit!")
        print("    (Remember: Gunicorn needs ~100MB extra overhead per worker)")
    else:
        print("\n✅ Safe Zone.")

except Exception as e:
    print(f"\n❌ Error loading files: {e}")
    print("Make sure the paths in this script match your actual folder structure.")