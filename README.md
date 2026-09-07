# mavplan

MAVLink mission planner — define drone waypoints and export to MAVLink, KML, or CSV.

Supports waypoints with position, altitude, speed, delay, and yaw control. Works with PX4, ArduPilot, and any MAVLink-compatible autopilot.

## Features

- Define missions with waypoints: latitude, longitude, altitude, speed, delay, yaw
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
# Define waypoints from arguments
mavplan waypoint add --lat 31.23 --lon 121.47 --alt 50 --speed 10
mavplan waypoint add --lat 31.24 --lon 121.48 --alt 50 --speed 10

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
from mavplan import Mission, Waypoint, ExportFormat

mission = Mission(name="Survey Pattern")
mission.add_waypoint(lat=31.23, lon=121.47, alt=50, speed=10)
mission.add_waypoint(lat=31.24, lon=121.48, alt=50, speed=10)

# Export
print(mission.to_kml())
print(mission.to_mavlink())
print(mission.to_csv())
```

## Mission File Format

Save and load missions as JSON:

```json
{
  "name": "Survey Pattern",
  "frame": "global",
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

## License

MIT
