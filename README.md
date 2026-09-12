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
- **Interop + actions** (v1.1): Import/export QGC `.plan` & WPL (Mission Planner/QGC), MAV_CMD DO_* action items, camera-trigger insertion
- **Teaching suite** (v1.3): Task briefs, automated grading, self-contained HTML score reports
- **Safety preflight** (v1.4): No-fly zone model, mission check (range/altitude/turns/battery margin), `lost-link` teaching demo
- **Survey & photogrammetry** (v1.5): Camera model (FOV/GSD/footprint), overlap-based lane & shutter spacing (`lawnmower --camera`), theoretical coverage validation, survey grading with GSD + side-overlap
- **Training operations** (v1.6): CLI zh-CN i18n, scenario preset library (8 templates), `grade batch` for CAAC class workflows
- **Teaching preview** (v1.7): offline HTML mission preview (`mission preview`), printable class overview (`class_summary.html`)
- **Export**: MAVLink waypoint file, QGC `.plan`, WPL, KML (Google Earth), CSV, GeoJSON

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

# --- Teaching preview (v1.7) ---
mavplan mission preview plan.json -o preview.html
mavplan mission preview plan.json -o preview.html --zones-json zones.json
mavplan class report reports/          # rebuild class_summary.html
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

### v1.10.1 (2026-09-12)
- Preflight: a mission with only one waypoint now returns an info-level `single_waypoint` finding instead of an empty all-clear (path/turn/battery cannot be assessed)

### v1.10.0 (2026-09-12)
- CLI: `mavplan mission check -o preflight.json` writes the `mavplan.preflight/1` report to a file (same exit code 2 on errors)

### v1.9.0 (2026-09-12)
- **Structured preflight**: `preflight_report()` returns `mavplan.preflight/1` (mission meta, summary, checks)
- CLI: `mavplan mission check --json` emits the same document; exit code 2 when errors are present
- Public API: `preflight_report` exported from `mavplan`

### v1.8.0 (2026-09-12)
- **GeoJSON export**: `Mission.to_geojson()` emits a FeatureCollection (waypoint Points + LineString path) for QGIS / web map overlays
- New CLI: `mavplan export geojson -o mission.geojson`
- Releases the v1.6–v1.7.2 work that had been on `main` without a GitHub Release (i18n, scenarios, batch grading, teaching preview, UTF-8 BOM fixes)

### v1.7.2 (2026-09-11)
- Fixed: `sniff_format` / `load_mission_file` rejected UTF-8 BOM on QGC WPL and `.plan` files (PowerShell `Set-Content -Encoding utf8` writes a BOM). `Mission.load` already accepted BOM; WPL/plan loaders now match.
- Fixed: `parse_wpl` strips a leading BOM from raw text
- Test suite: 283 → 286 tests (100% passing)

### v1.7.1 (2026-09-11)
- Fixed: `mavplan class report` crashed with `AttributeError: 'Command' object has no attribute 'DictReader'` because the `export csv` Click command shadowed the stdlib `csv` module in `cli.py`
- Fixed: `mavplan class report` crashed with `TypeError: ClassResult missing pass_threshold` when rebuilding HTML from `class_summary.csv`
- Test suite: 282 → 283 tests (100% passing)

### v1.7.0 (2026-09-11)
- **Teaching preview**: offline single-file HTML mission preview for classroom projection
- New module: `mavplan.preview_html` (`render_mission_preview`)
- New CLI: `mavplan mission preview [plan.json] -o preview.html` with optional `--zones-kml` / `--zones-json` overlay
- Preview shows: local ENU SVG map (waypoint numbers, heading arrows, lawnmower coverage bands, no-fly zones), altitude profile vs cumulative distance, click-to-highlight, waypoint table
- **Class overview HTML**: `grade batch` now also writes printable `class_summary.html`; `mavplan class report <dir>` rebuilds it from `class_summary.csv`
- Fixed: `Mission.load` and `load_zones_json` now accept UTF-8 BOM files (PowerShell `Set-Content -Encoding utf8` writes a BOM)
- Test suite: 270 → 282 tests (100% passing), zero new runtime dependencies

### v1.6.0 (2026-09-09)
- **Training operations edition**: complete the loop from "instructor prepares class" → "students fly" → "instructor grades the whole class"
- **CLI zh-CN i18n** (`mavplan.i18n`): all CLI help / errors / reports / grading comments are Chinese-first; `--lang zh-CN|en` flag and `LANG` env var honored
- **Scenario preset library** (`scenarios/*.yaml` + `mavplan.scenario`): 8 YAML templates — rectangle patrol, corridor transit, powerline inspection, agri spraying, search & rescue, bridge inspection, logistics delivery, lost-link demo
- **New CLI**: `mavplan scenario {list,show,run}` to load and instantiate a preset into a fresh `TaskSpec` + `Mission`
- **Batch class grading** (`mavplan.grade_batch` + `mavplan.class_summary`): `grade batch --roster roster.csv --logs logs/ --task plan.json --out reports/` grades every student in one pass and emits per-student HTML reports + a class summary CSV
- **New CLI**: `mavplan grade batch` and `mavplan class summary <reports-dir>`
- Test suite: 216 → 270 tests (100% passing), zero new runtime dependencies (YAML parsing uses stdlib `json` + a tiny home-grown reader)

### v1.5.0 (2026-09-09)
- **Survey & photogrammetry teaching suite**: camera model (sensor/focal/pixels → FOV, GSD, single-shot footprint), overlap-based lane & shutter spacing for `lawnmower --camera`, theoretical coverage validation, survey auto-grading (GSD + side-overlap) with Chinese lesson report, CLI smoke assets
- New modules: `mavplan.survey` (camera geometry + coverage math), `mavplan.report_html` extensions
- Test suite: 194 → 216 tests (100% passing), zero new runtime dependencies

### v1.4.0 (2026-09-09)
- **Safety preflight suite**: no-fly zone model (circle / polygon via KML / JSON), mission check (turn radius, bank angle, max range / altitude, zone intersection, battery margin), `simulate lost-link` teaching demo, preflight section merged into HTML score report, structured CLI smoke assets
- New modules: `mavplan.nofly`
- Test suite: 165 → 194 tests (100% passing), zero new runtime dependencies

### v1.3.0 (2026-09-09)
- **Teaching suite**: task briefs (`TaskSpec`), automated grading (`grade.py`), HTML score reports (`report_html.py`)
- New modules: `mavplan.taskspec`, `mavplan.grade`, `mavplan.report_html`, `mavplan.taskgen`
- New CLI: `mavplan task {new,generate,validate,show}`, `mavplan grade {run,batch,summary}`
- Test suite: 138 → 165 tests (100% passing), zero new runtime dependencies

### v1.2 — 部分并入 v1.7
- HTML mission preview shipped as **v1.7.0** (`mission preview`); flight replay (`analyze replay`) remains pending
- Original v1.2 slot is no longer a separate release line

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

## Related projects

- [mavplan-web](https://github.com/TianHengZhuang/mavplan-web) — offline browser console (Vue 3); [live demo](https://tianhengzhuang.github.io/mavplan-web/)
- [Chinese-WebNovel-Master](https://github.com/TianHengZhuang/Chinese-WebNovel-Master) — Chinese web-fiction agent workflow
- [One-click-AI-PPT-creation](https://github.com/TianHengZhuang/One-click-AI-PPT-creation) — topic → presentation deck skill

## License

MIT
