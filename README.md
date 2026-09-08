# mavplan

MAVLink mission planner — define drone waypoints, generate patterns, analyze flight logs, and connect to real autopilots.

Works with PX4, ArduPilot, and any MAVLink-compatible autopilot.

## Features

- **Mission planning** (v0.1): Define waypoints with position, altitude, speed, delay, yaw
- **Automated patterns** (v0.2): Lawn-mower, polygon scan, circular orbit generation
- **Flight log analysis** (v0.3): Parse CSV logs, compute stats, compare plan vs actual
- **MAVLink connection** (v0.4): Upload missions to autopilot, download from autopilot
- **KML import + templates** (v0.5): Import KML files as missions, use built-in templates
- **Mission simulation** (v0.6): Battery estimation, wind effects, geofence check, safety validation
- **Export**: MAVLink waypoint file, KML (Google Earth), CSV

## Install

```bash
pip install mavplan
# For MAVLink support (upload/download to real autopilot):
pip install mavplan[mavlink]
```

## CLI

```bash
# --- Mission planning ---
mavplan waypoint add --lat 31.23 --lon 121.47 --alt 50 --speed 10
mavplan waypoint list
mavplan mission save mission.json

# --- Automated patterns (v0.2) ---
mavplan generate lawnmower --corner1 31.230,121.470 --corner2 31.240,121.480 --alt 50
mavplan generate polygon --polygon 31.230,121.470 --polygon 31.240,121.470 --polygon 31.240,121.480 --alt 50
mavplan generate orbit --center 31.235,121.475 --radius 50 --alt 50 --points 12

# --- Flight log analysis (v0.3) ---
mavplan analyze log flight_log.csv
mavplan analyze kml flight_log.csv -o flight.kml
mavplan analyze compare flight_log.csv mission.json -o comparison.kml

# --- MAVLink connection (v0.4) ---
mavplan link status udp:127.0.0.1:14550
mavplan link upload udp:127.0.0.1:14550 mission.json
mavplan link download udp:127.0.0.1:14550 downloaded.json

# --- Mission simulation (v0.6) ---
mavplan simulate run mission.json --capacity 8000 --wind 5 --wind-dir headwind
mavplan simulate battery mission.json --capacity 8000
mavplan simulate geofence mission.json --max-range 1000
mavplan simulate with-tol mission.json -o mission_with_tol.json

# --- KML import + templates (v0.5) ---
mavplan template list
mavplan template load "Large Area Survey" -o my_mission.json
mavplan template import-kml site.kml --alt 60 -o mission.json
mavplan template export templates.json

# --- Export ---
mavplan export kml -o mission.kml
mavplan export mavlink -o mission.txt
mavplan export csv -o mission.csv
mavplan mission validate
```

## Python API

```python
from mavplan import (
    Mission, Waypoint,
    LawnMowerParams, PolygonScanParams, OrbitParams,
    generate_lawnmower, generate_polygon_scan, generate_orbit,
    FlightLog, parse_csv, compare_to_plan,
    KmlDocument, parse_kml, get_templates,
    MAVLinkConnection,
)

# Plan
mission = Mission(name="Survey")
mission.add_waypoint(lat=31.23, lon=121.47, alt=50)

# Patterns
params = LawnMowerParams(corner1=(31.230, 121.470), corner2=(31.240, 121.480), altitude=50)
for wp in generate_lawnmower(params):
    mission.add_waypoint(**wp.to_dict())

# Flight analysis
log = parse_csv("flight.csv")
stats = log.stats()
result = compare_to_plan(log, mission)

# KML import
doc = parse_kml("site.kml")
mission2 = doc.to_mission(default_alt=60)

# Templates
templates = get_templates()
print(templates[0].mission.to_kml())

# MAVLink upload (requires pymavlink)
conn = MAVLinkConnection.connect("udp:127.0.0.1:14550")
result = conn.upload_mission(mission)
conn.close()
```

## Changelog

### v1.0.0 (2026-09-08)
- **Stable release**: full feature set (mission planning, patterns, log analysis, MAVLink link, KML/templates, simulation) with a stable public API
- Fixed bug in `compare_to_plan()`: waypoint hit rates (10m/20m/50m) are now computed correctly as cumulative within-radius counts (previously a waypoint within 10m was not counted for the 20m/50m radii)
- Fixed packaging metadata: removed invalid PyPI classifier that blocked wheel builds
- CLI: `waypoint add` now validates coordinates before saving (rejects out-of-range lat/lon with a clear error)
- Test suite: 76 tests (100% passing) covering all public modules plus CLI end-to-end via `click.testing` (76% line coverage; `mavlink_link` remains lightly covered as it needs a live autopilot)
- Development status upgraded to Production/Stable

### v0.5.0 (2026-09-07)
- Added KML file import: parse Google Earth KML as mission waypoints
- Added built-in mission template library (5 templates: survey, inspection, emergency, patrol, mapping)
- `parse_kml()`, `KmlDocument`, `MissionTemplate`, `get_templates()`
- New CLI: `mavplan template` subcommand (list/load/import-kml/export)

### v0.6.0 (2026-09-07)
- Added mission simulation: battery estimation, wind effects, geofence check
- `BatteryModel`, `WindModel`, `SimulationParams`, `estimate_energy()`, `insert_takeoff_landing()`, `check_geofence()`, `generate_report()`
- New CLI: `mavplan simulate` subcommand (run/battery/geofence/with-tol)

### v0.4.0 (2026-09-07)
- Added MAVLink connection: upload/download missions to real autopilot
- `MAVLinkConnection.connect()`, `.upload_mission()`, `.download_mission()`
- New CLI: `mavplan link` subcommand (status/upload/download)
- Requires: `pip install pymavlink`

### v0.3.0 (2026-09-07)
- Added flight log analysis: parse CSV, compute stats, compare to plan
- `FlightLog`, `FlightStats`, `parse_csv`, `compare_to_plan`
- New CLI: `mavplan analyze` subcommand (log/kml/compare)

### v0.2.0 (2026-09-07)
- Added automated pattern generation: lawn-mower, polygon scan, orbit
- `LawnMowerParams`, `PolygonScanParams`, `OrbitParams`
- New CLI: `mavplan generate` subcommand

### v0.1.0 (2026-09-07)
- Initial release: waypoint CRUD, MAVLink/KML/CSV export, CLI

## Supported Autopilots

- PX4
- ArduPilot (Copter, Plane, Rover, Boat)
- Generic MAVLink systems

## License

MIT
