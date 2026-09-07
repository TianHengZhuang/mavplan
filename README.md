# mavplan

MAVLink mission planner — define drone waypoints and export to MAVLink, KML, or CSV.

Supports waypoints with position, altitude, speed, delay, and yaw control. Works with PX4, ArduPilot, and any MAVLink-compatible autopilot.

## Features

- Define missions with waypoints: latitude, longitude, altitude, speed, delay, yaw
- **Automated pattern generation** (v0.2):
  - Rectangular lawn-mower / survey pattern
  - Polygon-area scan
  - Circular orbit / loiter pattern
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
# Rectangular lawn-mower survey
mavplan generate lawnmower --corner1 31.230,121.470 --corner2 31.240,121.480 --alt 50 --spacing 20

# Polygon area scan (specify 3+ vertices)
mavplan generate polygon --polygon 31.230,121.470 --polygon 31.240,121.470 --polygon 31.240,121.480 --polygon 31.230,121.480 --alt 50

# Circular orbit / loiter
mavplan generate orbit --center 31.235,121.475 --radius 50 --alt 50 --points 12

# List current mission
mavplan mission list

# Export
mavplan export kml --output mission.kml
mavplan export mavlink --output mission.txt
mavplan export csv --output mission.csv

# Load / save missions
mavplan mission save mission.json
mavplan mission load mission.json

# Validate
mavplan mission validate
```

## Python API

```python
from mavplan import (
    Mission, Waypoint,
    LawnMowerParams, PolygonScanParams, OrbitParams,
    generate_lawnmower, generate_polygon_scan, generate_orbit,
)

# Manual waypoints
mission = Mission(name="Survey Pattern")
mission.add_waypoint(lat=31.23, lon=121.47, alt=50, speed=10)
mission.add_waypoint(lat=31.24, lon=121.48, alt=50, speed=10)

# --- Automated patterns (v0.2) ---
# Rectangular lawn-mower
params = LawnMowerParams(
    corner1=(31.230, 121.470),
    corner2=(31.240, 121.480),
    altitude=50, speed=10, lane_spacing=20,
)
mission2 = Mission(name="Survey")
for wp in generate_lawnmower(params):
    mission2.add_waypoint(**wp.to_dict())

# Polygon scan
params3 = PolygonScanParams(
    polygon=[(31.230, 121.470), (31.240, 121.470), (31.240, 121.480), (31.230, 121.480)],
    altitude=50, lane_spacing=20,
)
mission3 = Mission(name="Polygon Survey")
for wp in generate_polygon_scan(params3):
    mission3.add_waypoint(**wp.to_dict())

# Circular orbit
orbit_params = OrbitParams(
    center_lat=31.235, center_lon=121.475,
    radius=50, altitude=50, num_points=12,
)
mission4 = Mission(name="Loiter")
for wp in generate_orbit(orbit_params):
    mission4.add_waypoint(**wp.to_dict())

# Export any mission
print(mission.to_kml())
print(mission.to_mavlink())
print(mission.to_csv())
```

## Mission File Format

Save and load missions as JSON:

```json
{
  "name": "Survey Pattern",
  "frame": 3,
  "waypoints": [
    {"seq": 0, "lat": 31.23, "lon": 121.47, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999},
    {"seq": 1, "lat": 31.24, "lon": 121.48, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999}
  ]
}
```

## Supported Autopilots

- PX4
- ArduPilot (Copter, Plane, Rover, Boat)
- Generic MAVLink systems

## Changelog

### v0.2.0 (2026-09-07)
- Added automated pattern generation: lawn-mower, polygon scan, circular orbit
- `LawnMowerParams` / `PolygonScanParams` / `OrbitParams` dataclasses
- `generate_lawnmower()`, `generate_polygon_scan()`, `generate_orbit()` functions
- New `mavplan generate` CLI subcommand

### v0.1.0 (2026-09-07)
- Initial release: waypoint CRUD, MAVLink/KML/CSV export, CLI

## License

MIT
