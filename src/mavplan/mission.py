"""Mission container and export logic."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from .waypoint import Waypoint
from .actions import command_id, DO_SET_CAM_TRIGG_DIST, DO_SET_CAM_TRIGG_INTERVAL


class Mission:
    """A collection of waypoints forming a drone mission."""

    def __init__(self, name: str = "Untitled Mission", frame: int = 3, home: Optional[tuple] = None):
        self.name = name
        self.frame = frame  # MAV_FRAME: 0=global, 3=global relative alt
        self.home = home  # Optional (lat, lon, alt) home position
        self._waypoints: list[Waypoint] = []

    def add_waypoint(self, **kwargs) -> Waypoint:
        """Add a waypoint, auto-assigning its sequence number.

        Kwargs are passed to Waypoint().  Example::

            mission.add_waypoint(lat=31.23, lon=121.47, alt=50, speed=10)
        """
        wp = Waypoint(**kwargs)
        wp.seq = len(self._waypoints)
        wp.frame = self.frame
        self._waypoints.append(wp)
        return wp

    def insert_waypoint(self, index: int, **kwargs) -> Waypoint:
        """Insert a waypoint at ``index``, renumbering all following items.

        Kwargs are passed to Waypoint().  Example::

            mission.insert_waypoint(1, lat=31.23, lon=121.47, alt=50)
        """
        wp = Waypoint(**kwargs)
        self._waypoints.insert(index, wp)
        for i, existing in enumerate(self._waypoints):
            existing.seq = i
        return wp

    def add_action(
        self,
        after_seq: int,
        command: int | str,
        param1: float = 0.0,
        param2: float = 0.0,
        param3: float = 0.0,
        param4: float = 0.0,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        alt: Optional[float] = None,
    ) -> Waypoint:
        """Insert a DO_* action item right after ``after_seq``.

        When lat/lon/alt are omitted the action inherits the position of the
        waypoint at ``after_seq`` (MAVLink convention: DO_* items usually
        repeat the preceding navigation point coordinates).
        """
        cmd = command_id(command)
        if cmd is None:
            raise ValueError(f"Unknown MAV_CMD: {command!r}")
        ref = self._waypoints[after_seq]
        wp = self.insert_waypoint(
            after_seq + 1,
            lat=ref.lat if lat is None else lat,
            lon=ref.lon if lon is None else lon,
            alt=ref.alt if alt is None else alt,
            command=cmd,
            frame=ref.frame,
        )
        wp.delay = param1
        wp.acceptance_radius = param2
        wp.orbit = param3
        wp.yaw = param4
        return wp

    def add_camera_trigger(
        self,
        mode: str = "distance",
        value: float = 25.0,
        after_seq: int = 0,
    ) -> Waypoint:
        """Insert a camera-trigger DO_* action right after ``after_seq``.

        ``mode="distance"`` inserts DO_SET_CAM_TRIGG_DIST (trigger every
        ``value`` metres of travel); ``mode="time"`` inserts
        DO_SET_CAM_TRIGG_INTERVAL (trigger every ``value`` seconds).
        The action inherits the position of waypoint ``after_seq``.
        """
        if mode == "distance":
            return self.add_action(
                after_seq, DO_SET_CAM_TRIGG_DIST, param1=float(value)
            )
        if mode == "time":
            return self.add_action(
                after_seq, DO_SET_CAM_TRIGG_INTERVAL, param1=float(value)
            )
        raise ValueError("mode must be 'distance' or 'time'")

    def remove_waypoint(self, seq: int) -> None:
        """Remove the waypoint with the given sequence number."""
        for i, wp in enumerate(self._waypoints):
            if wp.seq == seq:
                del self._waypoints[i]
                for j, remaining in enumerate(self._waypoints):
                    remaining.seq = j
                return
        raise IndexError(f"No waypoint with seq {seq}")

    def waypoints(self) -> list[Waypoint]:
        return list(self._waypoints)

    def __len__(self) -> int:
        return len(self._waypoints)

    def __getitem__(self, index: int) -> Waypoint:
        return self._waypoints[index]

    def validate(self) -> list[str]:
        """Full mission validation. Returns list of error messages."""
        errors = []
        if not self._waypoints:
            errors.append("Mission has no waypoints")
            return errors

        for wp in self._waypoints:
            errors.extend(wp.validate())

        # Check home vs waypoint distance (sanity check)
        home = self._waypoints[0]
        for i, wp in enumerate(self._waypoints[1:], start=1):
            dist = home.distance_to(wp)
            if dist > 50000:
                errors.append(
                    f"Waypoint {i} is {dist/1000:.1f}km from home — "
                    "verify this is intentional"
                )

        return errors

    # ------------------------------------------------------------------
    # Export formats
    # ------------------------------------------------------------------

    def total_distance(self) -> float:
        """Total mission path length in metres."""
        if len(self._waypoints) < 2:
            return 0.0
        return sum(
            self._waypoints[i].distance_to(self._waypoints[i + 1])
            for i in range(len(self._waypoints) - 1)
        )

    def estimated_duration(self, hover_time: float = 5.0) -> float:
        """Estimated flight time in seconds.

        Assumes 10 m/s cruise speed and adds `hover_time` seconds per
        waypoint (for turn / settle).  Override by passing a different
        hover_time value.
        """
        if len(self._waypoints) < 2:
            return 0.0

        cruise_speed = 10.0
        distances = [
            self._waypoints[i].distance_to(self._waypoints[i + 1])
            for i in range(len(self._waypoints) - 1)
        ]
        cruise_time = sum(d / cruise_speed for d in distances)
        hover = hover_time * len(self._waypoints)
        delays = sum(wp.delay for wp in self._waypoints)
        return cruise_time + hover + delays

    def to_dict(self) -> dict:
        data: dict = {
            "name": self.name,
            "frame": self.frame,
        }
        if self.home is not None:
            data["home"] = list(self.home)
        data["waypoints"] = [wp.to_dict() for wp in self._waypoints]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Mission:
        mission = cls(name=data.get("name", "Untitled"), frame=data.get("frame", 3))
        if data.get("home") is not None:
            mission.home = tuple(data["home"])
        for wp_data in data.get("waypoints", []):
            mission.add_waypoint(**Waypoint.from_dict(wp_data).to_dict())
        return mission

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> Mission:
        with open(path, "r", encoding="utf-8-sig") as f:
            return cls.from_dict(json.load(f))

    # ------------------------------------------------------------------
    # MAVLink waypoint file (QGroundControl / Mission Planner format)
    # ------------------------------------------------------------------
    def to_mavlink(self) -> str:
        """MAVLink mission file (QGC / MP compatible).

        Format: one QGC-item header line + one line per waypoint.
        """
        lines = ["QGC WPL 120"]
        for wp in self._waypoints:
            item = wp.to_mavlink_item()
            vals = [
                item["seq"],
                item["current"],
                item["frame"],
                item["command"],
                item["autocontinue"],
                round(item["param1"], 1),  # delay
                round(item["param2"], 1),  # acceptance radius
                round(item["param3"], 1),  # orbit
                round(item["param4"], 1),  # yaw
                round(item["x"], 7),  # lat
                round(item["y"], 7),  # lon
                round(item["z"], 2),  # alt
            ]
            lines.append("\t".join(str(v) for v in vals))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # KML (Google Earth / Maps)
    # ------------------------------------------------------------------
    def to_kml(self) -> str:
        """KML representation for Google Earth / Maps import."""
        waypoint_coords = "\n".join(
            f"          {wp.lon:.7f},{wp.lat:.7f},{wp.alt:.1f}"
            for wp in self._waypoints
        )
        placemark_items = ""
        for wp in self._waypoints:
            placemark_items += f"""\
        <Placemark>
          <name>WP{wp.seq}</name>
          <description>Alt: {wp.alt:.1f}m | Speed: {wp.speed:.0f}m/s | Delay: {wp.delay:.0f}s</description>
          <Point>
            <coordinates>{wp.lon:.7f},{wp.lat:.7f},{wp.alt:.1f}</coordinates>
          </Point>
        </Placemark>
"""
        return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{_escape_xml(self.name)}</name>
    <description>MAVLink mission: {len(self._waypoints)} waypoints, {self.total_distance()/1000:.1f}km total</description>
    <Style id="waypoint">
      <IconStyle>
        <color>ff00ff00</color>
        <scale>1.2</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>
        </Icon>
      </IconStyle>
    </Style>
    <Style id="track">
      <LineStyle>
        <color>ff0000ff</color>
        <width>3</width>
      </LineStyle>
    </Style>
    <Folder>
      <name>Waypoints</name>
{placemark_items}    </Folder>
    <Placemark>
      <name>Flight Path</name>
      <styleUrl>#track</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>
{waypoint_coords}
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""

    # ------------------------------------------------------------------
    # GeoJSON (GIS / web map overlay)
    # ------------------------------------------------------------------
    def to_geojson(self) -> dict:
        """GeoJSON FeatureCollection: waypoint Points + a LineString path.

        Coordinates are ``[lon, lat, alt_m]`` per RFC 7946. Suitable for
        QGIS, GeoJSON.io, Mapbox, and Leaflet overlays.
        """
        features: list[dict] = []
        for wp in self._waypoints:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(wp.lon, 7), round(wp.lat, 7), round(wp.alt, 2)],
                    },
                    "properties": {
                        "seq": wp.seq,
                        "speed": wp.speed,
                        "delay": wp.delay,
                        "yaw": wp.yaw,
                        "command": wp.command,
                        "frame": wp.frame,
                        "kind": "waypoint",
                    },
                }
            )
        if len(self._waypoints) >= 2:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [round(wp.lon, 7), round(wp.lat, 7), round(wp.alt, 2)]
                            for wp in self._waypoints
                        ],
                    },
                    "properties": {
                        "name": self.name,
                        "kind": "path",
                        "distance_m": round(self.total_distance(), 1),
                        "waypoint_count": len(self._waypoints),
                    },
                }
            )
        return {
            "type": "FeatureCollection",
            "features": features,
        }

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------
    def to_csv(self) -> str:
        """Tab-separated CSV with one header row + one row per waypoint."""
        rows = [
            "seq\tlat\tlon\talt\tspeed\tdelay\tyaw\t"
            "acceptance_radius\torbit\tcommand\tframe\tautocontinue"
        ]
        for wp in self._waypoints:
            rows.append(
                f"{wp.seq}\t{wp.lat:.7f}\t{wp.lon:.7f}\t{wp.alt:.2f}\t"
                f"{wp.speed:.1f}\t{wp.delay:.1f}\t{wp.yaw:.1f}\t"
                f"{wp.acceptance_radius:.1f}\t{wp.orbit:.1f}\t"
                f"{wp.command}\t{wp.frame}\t{wp.autocontinue}"
            )
        return "\n".join(rows)


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
