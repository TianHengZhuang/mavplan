"""Flight log parsing and analysis for MAVLink missions.

Supports:
  - CSV logs exported from QGroundControl or Mission Planner
  - JSON mission files saved by mavplan
  - Generic tab/CSV files with lat/lon/alt columns
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, TextIO

from .mission import Mission
from .waypoint import Waypoint


# ------------------------------------------------------------------
# Dataclasses
# ------------------------------------------------------------------

@dataclass
class FlightPoint:
    """A single point in a flight log."""
    lat: float
    lon: float
    alt: float          # metres
    speed: float = 0.0  # m/s
    time_s: float = 0.0 # seconds since start
    heading: float = 0.0  # degrees 0-360

    def distance_to(self, other: FlightPoint) -> float:
        """Haversine distance in metres."""
        R = 6_371_000.0
        phi1 = math.radians(self.lat)
        phi2 = math.radians(other.lat)
        dphi = math.radians(other.lat - self.lat)
        dlam = math.radians(other.lon - self.lon)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass
class FlightStats:
    """Statistics computed from a flight log."""
    total_distance_m: float
    max_altitude_m: float
    min_altitude_m: float
    flight_duration_s: float
    avg_speed_mps: float
    max_speed_mps: float
    num_points: int
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    max_altitude_change_m: float  # difference between highest and lowest point
    horizontal_distance_m: float  # straight-line start-to-end distance


@dataclass
class FlightLog:
    """A parsed flight log."""
    points: list[FlightPoint] = field(default_factory=list)
    source_file: str = ""

    def __len__(self) -> int:
        return len(self.points)

    def stats(self) -> FlightStats:
        if not self.points:
            return FlightStats(
                total_distance_m=0, max_altitude_m=0, min_altitude_m=0,
                flight_duration_s=0, avg_speed_mps=0, max_speed_mps=0,
                num_points=0, start_lat=0, start_lon=0, end_lat=0, end_lon=0,
                max_altitude_change_m=0, horizontal_distance_m=0,
            )

        alts = [p.alt for p in self.points]
        speeds = [p.speed for p in self.points if p.speed > 0]

        total_dist = sum(
            self.points[i].distance_to(self.points[i + 1])
            for i in range(len(self.points) - 1)
        )
        horizontal_dist = self.points[0].distance_to(self.points[-1])

        return FlightStats(
            total_distance_m=total_dist,
            max_altitude_m=max(alts),
            min_altitude_m=min(alts),
            flight_duration_s=self.points[-1].time_s - self.points[0].time_s,
            avg_speed_mps=sum(speeds) / len(speeds) if speeds else 0.0,
            max_speed_mps=max(speeds) if speeds else 0.0,
            num_points=len(self.points),
            start_lat=self.points[0].lat,
            start_lon=self.points[0].lon,
            end_lat=self.points[-1].lat,
            end_lon=self.points[-1].lon,
            max_altitude_change_m=max(alts) - min(alts),
            horizontal_distance_m=horizontal_dist,
        )

    def to_kml(self, name: str = "Flight Path", color: str = "ff0000ff") -> str:
        """KML representation of the flight path.

        Args:
            name: KML Placemark name.
            color: KML color in aabbggrr format (default: blue).
        """
        if not self.points:
            return ""

        coords = "\n".join(
            f"          {p.lon:.7f},{p.lat:.7f},{p.alt:.1f}"
            for p in self.points
        )
        placemarks = ""
        for i, p in enumerate(self.points):
            if i % max(1, len(self.points) // 20) == 0:  # up to 20 markers
                placemarks += f"""\
        <Placemark>
          <name>t+{int(p.time_s)}s</name>
          <description>Alt: {p.alt:.1f}m | Speed: {p.speed:.1f}m/s | HDG: {p.heading:.0f}</description>
          <Point>
            <coordinates>{p.lon:.7f},{p.lat:.7f},{p.alt:.1f}</coordinates>
          </Point>
        </Placemark>
"""
        return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{_esc(name)}</name>
    <description>Flight log: {len(self.points)} points</description>
    <Style id="track">
      <LineStyle>
        <color>{color}</color>
        <width>3</width>
      </LineStyle>
    </Style>
    <Folder>
      <name>Flight Path</name>
{placemarks}    </Folder>
    <Placemark>
      <name>{_esc(name)}</name>
      <styleUrl>#track</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>
{coords}
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""

    def to_csv(self) -> str:
        """Export flight log as CSV."""
        rows = ["time_s\tlat\tlon\talt\tspeed\theading"]
        for p in self.points:
            rows.append(
                f"{p.time_s:.2f}\t{p.lat:.7f}\t{p.lon:.7f}\t{p.alt:.2f}\t"
                f"{p.speed:.2f}\t{p.heading:.1f}"
            )
        return "\n".join(rows)


# ------------------------------------------------------------------
# Parsers
# ------------------------------------------------------------------

def _detect_delimiter(sample: str) -> str:
    """Detect CSV delimiter (comma, tab, or semicolon)."""
    if "\t" in sample:
        return "\t"
    if ";" in sample and "," not in sample:
        return ";"
    return ","


def _sniff_columns(header_line: str, delimiter: str) -> dict[str, int]:
    """Map column names to indices. Returns empty dict if required cols missing."""
    parts = [c.strip().lower() for c in header_line.split(delimiter)]
    col_map = {}
    for i, name in enumerate(parts):
        name = name.strip()
        # Match common column name variants
        if name in ("lat", "latitude", "lat_gps", "gps_lat", "pos_lat"):
            col_map["lat"] = i
        elif name in ("lon", "lng", "longitude", "lon_gps", "gps_lon", "pos_lon"):
            col_map["lon"] = i
        elif name in ("alt", "altitude", "alt_rel", "altitude_relative"):
            col_map["alt"] = i
        elif name in ("time", "time_s", "timestamp", "time_sec", "elapsed_sec"):
            col_map["time"] = i
        elif name in ("speed", "ground_speed", "speed_m_s", "vel"):
            col_map["speed"] = i
        elif name in ("heading", "hdg", "yaw", "attitude_yaw"):
            col_map["heading"] = i
    return col_map


def parse_csv(path: str | Path) -> FlightLog:
    """Parse a CSV flight log file.

    Attempts to auto-detect columns: lat/lon/alt are required; time,
    speed, heading are optional.

    Supports files exported from QGroundControl, Mission Planner,
    and generic GPS logger CSV files.

    Args:
        path: Path to the CSV file.

    Returns:
        FlightLog with parsed points.

    Raises:
        ValueError: If the file cannot be parsed.
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"File not found: {path}")

    # Read raw content
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    if len(lines) < 2:
        raise ValueError("CSV file has fewer than 2 lines")

    delimiter = _detect_delimiter(lines[0])
    col_map = _sniff_columns(lines[0], delimiter)

    if "lat" not in col_map or "lon" not in col_map:
        raise ValueError(
            f"CSV must contain latitude and longitude columns. "
            f"Found columns: {lines[0]}"
        )

    has_alt = "alt" in col_map
    has_time = "time" in col_map
    has_speed = "speed" in col_map
    has_heading = "heading" in col_map

    points: list[FlightPoint] = []
    for line_num, line in enumerate(lines[1:], start=2):
        parts = [p.strip() for p in line.split(delimiter)]
        if len(parts) <= max(col_map.values()):
            continue  # Skip malformed rows

        try:
            lat = float(parts[col_map["lat"]])
            lon = float(parts[col_map["lon"]])
        except (ValueError, IndexError):
            continue  # Skip rows with invalid coordinates

        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            continue  # Skip obviously invalid coordinates

        alt = float(parts[col_map["alt"]]) if has_alt else 0.0
        time_s = float(parts[col_map["time"]]) if has_time else (line_num - 2) * 1.0
        speed = 0.0
        if has_speed:
            try:
                speed = float(parts[col_map["speed"]])
            except (ValueError, IndexError):
                pass
        heading = 0.0
        if has_heading:
            try:
                heading = float(parts[col_map["heading"]]) % 360
            except (ValueError, IndexError):
                pass

        points.append(FlightPoint(
            lat=lat, lon=lon, alt=alt,
            speed=speed, time_s=time_s, heading=heading,
        ))

    if not points:
        raise ValueError("No valid GPS points found in CSV")

    log = FlightLog(points=points, source_file=str(path))
    return log


def parse_mavplan_json(path: str | Path) -> FlightLog:
    """Parse a mavplan JSON mission file as a flight log.

    Uses the waypoints as if they were a planned route (no telemetry data).
    Speed defaults to 10 m/s for estimation purposes.

    Args:
        path: Path to the JSON mission file.

    Returns:
        FlightLog with waypoints treated as flight path.
    """
    mission = Mission.load(path)
    points: list[FlightPoint] = []
    for i, wp in enumerate(mission.waypoints()):
        # Estimate time assuming 10 m/s cruise speed between waypoints
        if i == 0:
            t = 0.0
        else:
            prev = mission.waypoints()[i - 1]
            dist = prev.distance_to(wp)
            t = points[-1].time_s + dist / 10.0
        points.append(FlightPoint(
            lat=wp.lat, lon=wp.lon, alt=wp.alt,
            speed=wp.speed if wp.speed > 0 else 10.0,
            time_s=t, heading=wp.yaw if wp.yaw != -9999 else 0.0,
        ))
    return FlightLog(points=points, source_file=str(path))


# ------------------------------------------------------------------
# Mission comparison
# ------------------------------------------------------------------

def compare_to_plan(flight: FlightLog, plan: Mission) -> dict:
    """Compare an actual flight log against a planned mission.

    Args:
        flight: Parsed FlightLog with telemetry.
        plan: Planned Mission.

    Returns:
        Dict with comparison metrics.
    """
    if not flight.points or not plan.waypoints():
        return {"error": "Need both flight log and plan waypoints"}

    plan_wps = plan.waypoints()

    # Distance coverage: how much of the planned route was flown
    total_plan_dist = plan.total_distance()
    flight_dist = flight.stats().total_distance_m

    # Waypoint hit rate: what fraction of planned waypoints were approached
    hit_radii = [10, 20, 50]  # metres
    hit_counts = {r: 0 for r in hit_radii}
    for pwp in plan_wps:
        for fp in flight.points:
            d = pwp.distance_to(fp)
            for r in hit_radii:
                if d <= r:
                    hit_counts[r] += 1
                    break

    # Altitude deviation: mean absolute altitude error
    alt_errors = []
    if len(flight.points) >= len(plan_wps):
        step = max(1, len(flight.points) // len(plan_wps))
        for i in range(0, len(flight.points), step):
            idx = min(i // step, len(plan_wps) - 1)
            alt_errors.append(abs(flight.points[i].alt - plan_wps[idx].alt))

    return {
        "plan_distance_m": round(total_plan_dist, 1),
        "flight_distance_m": round(flight_dist, 1),
        "coverage_ratio": round(flight_dist / total_plan_dist, 2) if total_plan_dist > 0 else 0,
        "waypoint_hits_10m": hit_counts[10],
        "waypoint_hits_20m": hit_counts[20],
        "waypoint_hits_50m": hit_counts[50],
        "total_plan_waypoints": len(plan_wps),
        "avg_altitude_error_m": round(sum(alt_errors) / len(alt_errors), 1) if alt_errors else 0,
    }


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
