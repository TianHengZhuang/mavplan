# mavplan

MAVLink mission planner — define drone waypoints and export to MAVLink, KML, or CSV.

Supports waypoints with position, altitude, speed, delay, and yaw control. Works with PX4, ArduPilot, and any MAVLink-compatible autopilot.

## Features

- Define missions with waypoints: latitude, longitude, altitude, speed, delay, yaw
- **Automated pattern generation** (v0.2):
  - Rectangular lawn-mower / survey pattern
  - Polygon-area scan
  - Circular orbit / loiter pattern
- **Flight log analysis** (v0.3):
  - Parse CSV flight logs (QGroundControl, Mission Planner, generic GPS CSV)
  - Compute flight statistics: distance, altitude, speed, duration
  - Compare actual flight against planned mission
  - Export flight path as KML overlay
- Validate missions (bounds, sequence checks)
- Export to:
  - **MAVLink waypoint file** (compatible with QGroundControl, Mission Planner)
  - **KML** (Google Earth / Google Maps)
  - **CSV** (spreadsheet import)
- Python API for programmatic mission generation

## Install

```bash
pip install mavplan
```

## CLI

```bash
# Manual waypoint entry
mavplan waypoint add --lat 31.23 --lon 121.47 --alt 50 --speed 10
mavplan waypoint add --lat 31.24 --lon 121.48 --alt 50 --speed 10

# --- Automated pattern generation (v0.2) ---
mavplan generate lawnmower --corner1 31.230,121.470 --corner2 31.240,121.480 --alt 50 --spacing 20
mavplan generate polygon --polygon 31.230,121.470 --polygon 31.240,121.470 --polygon 31.240,121.480 --alt 50
mavplan generate orbit --center 31.235,121.475 --radius 50 --alt 50 --points 12

# --- Flight log analysis (v0.3) ---
mavplan analyze log flight_log.csv
mavplan analyze kml flight_log.csv -o flight.kml
mavplan analyze compare flight_log.csv mission.json -o comparison.kml

# List / export / validate
mavplan mission list
mavplan export kml --output mission.kml
mavplan export mavlink --output mission.txt
mavplan export csv --output mission.csv
mavplan mission save mission.json
mavplan mission load mission.json
mavplan mission validate
```

## Python API

```python
from mavplan import (
    Mission, Waypoint,
    LawnMowerParams, PolygonScanParams, OrbitParams,
    generate_lawnmower, generate_polygon_scan, generate_orbit,
    FlightLog, FlightStats, parse_csv, compare_to_plan,
)

# Plan a mission
mission = Mission(name="Survey")
mission.add_waypoint(lat=31.23, lon=121.47, alt=50, speed=10)

# Automated patterns
params = LawnMowerParams(corner1=(31.230, 121.470), corner2=(31.240, 121.480), altitude=50)
for wp in generate_lawnmower(params):
    mission.add_waypoint(**wp.to_dict())

# Analyze a flight log
log = parse_csv("flight_log.csv")
stats = log.stats()
print(f"Distance: {stats.total_distance_m/1000:.2f} km")
print(f"Max altitude: {stats.max_altitude_m:.1f} m")
print(f"Duration: {stats.flight_duration_s/60:.1f} min")

# Compare actual vs planned
result = compare_to_plan(log, mission)
print(f"Coverage: {result['coverage_ratio']:.0%}")
print(f"Waypoint hit rate (20m): {result['waypoint_hits_20m']}/{result['total_plan_waypoints']}")

# Export KML
print(mission.to_kml())
print(log.to_kml())
```

## Mission File Format

Save and load missions as JSON:

```json
{
  "name": "Survey Pattern",
  "frame": 3,
  "waypoints": [
    {"seq": 0, "lat": 31.23, "lon": 121.47, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999}
  ]
}
```

## Supported Autopilots

- PX4
- ArduPilot (Copter, Plane, Rover, Boat)
- Generic MAVLink systems

## Changelog

### v0.3.0 (2026-09-07)
- Added flight log analysis: `analyze log`, `analyze kml`, `analyze compare`
- `FlightLog` / `FlightStats` / `parse_csv` / `compare_to_plan`
- Auto-detect CSV columns (lat/lon/alt/time/speed/heading)
- KML overlay: planned route (green) vs actual flight (blue)
- Waypoint hit rate and altitude deviation metrics

### v0.2.0 (2026-09-07)
- Added automated pattern generation: lawn-mower, polygon scan, circular orbit
- `LawnMowerParams` / `PolygonScanParams` / `OrbitParams`
- New `mavplan generate` CLI subcommand

### v0.1.0 (2026-09-07)
- Initial release: waypoint CRUD, MAVLink/KML/CSV export, CLI

## License

MIT
