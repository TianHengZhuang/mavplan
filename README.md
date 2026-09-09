# mavplan

MAVLink mission planner — define drone waypoints, generate patterns, analyze flight logs, and connect to real autopilots.

Works with PX4, ArduPilot, and any MAVLink-compatible autopilot.

## Current release

**v1.5.0** adds a training-oriented workflow on top of mission planning:

- Task generation, automated grading, and self-contained HTML score reports
- Preflight checks for no-fly zones, range, altitude, turns, and battery margin
- Survey and photogrammetry calculations for camera field of view, GSD, overlap, lane spacing, and coverage validation

The project currently has 216 passing tests. See the [roadmap](docs/ROADMAP.md) for completed milestones and planned visual mission previews.

## Features

- **Mission planning** (v0.1): Define waypoints with position, altitude, speed, delay, yaw
- **Automated patterns** (v0.2): Lawn-mower, polygon scan, circular orbit generation
- **Flight log analysis** (v0.3): Parse CSV logs, compute stats, compare plan vs actual
- **MAVLink connection** (v0.4): Upload missions to autopilot, download from autopilot
- **KML import + templates** (v0.5): Import KML files as missions, use built-in templates
- **Mission simulation** (v0.6): Battery estimation, wind effects, geofence check, safety validation
- **Interop + actions** (v1.1): Import/export QGC `.plan` & WPL (Mission Planner/QGC), MAV_CMD DO_* action items, camera-trigger insertion
- **Export**: MAVLink waypoint file, QGC `.plan`, WPL, KML (Google Earth), CSV

## Install

```bash
git clone https://github.com/TianHengZhuang/mavplan.git
cd mavplan
python -m pip install .

# Optional MAVLink support for upload/download to a real autopilot:
python -m pip install pymavlink
```

`mavplan` is not published on PyPI yet, so install it from this repository.

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

### v1.5.0 (2026-09-09)
- Added survey and photogrammetry training: camera models, GSD and overlap calculations, automatic lane spacing, shutter spacing, and coverage validation
- Added task-generation, grading, and HTML reporting workflows for training scenarios
- Added preflight safety checks and no-fly-zone validation
- Test suite: 216 passing tests

### v1.1.0 (2026-09-08)
- **Interop layer**: two-way mission file conversion with real-world ground stations
- QGroundControl/Mission Planner **WPL import**: `parse_wpl()` + `mavplan mission import <file>` auto-detects WPL / `.plan` / native JSON; leading HOME item becomes `mission.home`
- **QGC `.plan` export/import**: `to_qgc_plan()` / `parse_qgc_plan()` / `save_qgc_plan()` + `mavplan export plan`; geo-fence & rally sections carried through (empty on export)
- **Mission home position**: `Mission(home=(lat, lon, alt))`, persisted in native JSON
- **MAV_CMD action layer**: `mavplan.actions` constants + `command_id()`/`command_name()`/`is_action()`; `Mission.add_action()`, `Mission.add_camera_trigger()`
- New CLI: `mavplan waypoint action <seq> --command DO_X` (insert DO_* item after a waypoint), `mavplan mission camera --mode distance|time --value N` (photo every N m / N s), `mavplan export wpl`
- `waypoint list` now tags non-navigation items, e.g. `[DO_SET_CAM_TRIGG_DIST]`
- Test suite: 138 tests (100% passing), zero new runtime dependencies

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
