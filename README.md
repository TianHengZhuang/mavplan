# mavplan

MAVLink mission planner — define drone waypoints, generate patterns, analyze flight logs, and connect to real autopilots.

Works with PX4, ArduPilot, and any MAVLink-compatible autopilot.

## Features

- **Mission planning** (v0.1): Define waypoints with position, altitude, speed, delay, yaw
- **Automated patterns** (v0.2): Lawn-mower, polygon scan, circular orbit generation
- **Flight log analysis** (v0.3): Parse CSV logs, compute stats, compare plan vs actual
- **MAVLink connection** (v0.4): Upload missions to autopilot, download from autopilot
- **KML import + templates** (v0.5): Import KML files as missions, use built-in templates
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

### v0.5.0 (2026-09-07)
- Added KML file import: parse Google Earth KML as mission waypoints
- Added built-in mission template library (5 templates: survey, inspection, emergency, patrol, mapping)
- `parse_kml()`, `KmlDocument`, `MissionTemplate`, `get_templates()`
- New CLI: `mavplan template` subcommand (list/load/import-kml/export)

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
