"""Task specification for training exams (v1.3 teaching suite).

A ``TaskSpec`` describes one CAAC-style beyond-visual-line-of-sight (BVLOS)
route-planning exam brief as JSON: takeoff/landing home, required
checkpoints (waypoints / areas), altitude & speed windows, time and
distance limits, plus no-fly zones the trainee flight must avoid.

Module also carries the small geometry helpers used by the grading engine
(distance, point-in-circle, segment-circle intersection), implemented in
local ENU projection so no geospatial dependency is needed.

Design notes:
  - No-fly zones are circles for v1.3 (polygon model lands in v1.4);
    the ``kind`` field keeps the door open for future extension.
  - Every coordinate is WGS84 lat/lon; radii and limits are metres.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Rough metre-per-degree scale at Shanghai training latitudes (31.x N).
_M_PER_DEG_LAT = 111_320.0


def _to_local_xy(lat: float, lon: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    """Project lat/lon to local east/north metres around a reference point.

    Simple equirectangular approximation, accurate enough for the kilometre
    scale of training tasks (error < 0.1% over 10 km).
    """
    x = (lon - ref_lon) * _M_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    y = (lat - ref_lat) * _M_PER_DEG_LAT
    return x, y


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points in metres."""
    R = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point_in_circle(lat: float, lon: float, c_lat: float, c_lon: float, radius_m: float) -> bool:
    """True when ``(lat, lon)`` lies strictly inside the circle."""
    return haversine_m(lat, lon, c_lat, c_lon) < radius_m


def segment_intersects_circle(
    lat1: float, lon1: float, lat2: float, lon2: float,
    c_lat: float, c_lon: float, radius_m: float,
) -> bool:
    """True when the geodesic segment (p1-p2) cuts through the circle.

    The segment is checked in local ENU projection. A trajectory that clips
    the circle boundary exactly (tangent) does NOT count as entering the
    zone — matching the v1.4 acceptance rule that boundary tangency is a
    separate geometric case.
    """
    ax, ay = _to_local_xy(lat1, lon1, c_lat, c_lon)
    bx, by = _to_local_xy(lat2, lon2, c_lat, c_lon)
    dx = bx - ax
    dy = by - ay

    # Degenerate segment (duplicate consecutive points): fall back to point test.
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay) < radius_m

    # Project circle centre (origin) onto the segment line, clamp to segment.
    t = -(ax * dx + ay * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px = ax + t * dx
    py = ay + t * dy
    return math.hypot(px, py) < radius_m


@dataclass
class Zone:
    """A no-fly zone (v1.3: circle; ``kind`` reserved for polygon in v1.4)."""
    name: str
    lat: float
    lon: float
    radius_m: float = 50.0
    kind: str = "circle"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "lat": round(self.lat, 7),
            "lon": round(self.lon, 7),
            "radius_m": round(self.radius_m, 1),
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Zone:
        return cls(
            name=str(data.get("name", "禁飞区")),
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            radius_m=float(data.get("radius_m", 50.0)),
            kind=str(data.get("kind", "circle")),
        )


@dataclass
class CheckPoint:
    """A required checkpoint the trainee route must reach.

    ``kind="point"`` means "pass within ``radius_m`` of this waypoint";
    ``kind="area"`` means "enter a circular region of radius ``radius_m``
    centred at (lat, lon)" (used for required operating areas).
    """
    name: str
    lat: float
    lon: float
    radius_m: float = 20.0
    kind: str = "point"  # "point" | "area"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "lat": round(self.lat, 7),
            "lon": round(self.lon, 7),
            "radius_m": round(self.radius_m, 1),
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CheckPoint:
        return cls(
            name=str(data.get("name", "必达点")),
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            radius_m=float(data.get("radius_m", 20.0)),
            kind=str(data.get("kind", "point")),
        )


@dataclass
class TaskSpec:
    """A route-planning exam brief.

    Attributes:
        name: Task title (shown in the score report).
        description: Human-readable mission text for the student.
        difficulty: easy / medium / hard (informational; set by generator).
        home: (lat, lon, alt) takeoff/landing point.
        required: List[CheckPoint] — must-fly waypoints / areas.
        altitude_range: (min_alt_m, max_alt_m) cruise altitude window.
        speed_range: (min_speed_mps, max_speed_mps) cruise speed window.
        max_time_s: Time limit for the whole flight (seconds).
        max_distance_m: Maximum allowed flight distance (metres).
        no_fly_zones: List[Zone] the flight must not enter.
    """
    name: str = "航线规划考核任务"
    description: str = ""
    difficulty: str = "easy"
    home: tuple = (31.20, 121.40, 0.0)
    required: list[CheckPoint] = field(default_factory=list)
    altitude_range: tuple = (50.0, 80.0)
    speed_range: tuple = (8.0, 12.0)
    max_time_s: float = 600.0
    max_distance_m: float = 5000.0
    no_fly_zones: list[Zone] = field(default_factory=list)

    # ------------------------------------------------------------------
    def required_points(self) -> list[CheckPoint]:
        """Checkpoints with kind == 'point'."""
        return [cp for cp in self.required if cp.kind == "point"]

    def required_areas(self) -> list[CheckPoint]:
        """Checkpoints with kind == 'area'."""
        return [cp for cp in self.required if cp.kind == "area"]

    def validate(self) -> list[str]:
        """Return list of validation errors (empty when valid)."""
        errors: list[str] = []
        if not -90 <= self.home[0] <= 90 or not -180 <= self.home[1] <= 180:
            errors.append(f"home 坐标非法: {self.home}")
        for cp in self.required:
            if not -90 <= cp.lat <= 90 or not -180 <= cp.lon <= 180:
                errors.append(f"必达点「{cp.name}」坐标非法")
            if cp.radius_m <= 0:
                errors.append(f"必达点「{cp.name}」半径必须大于 0")
        if self.altitude_range[0] > self.altitude_range[1]:
            errors.append("高度窗口下限大于上限")
        if self.speed_range[0] > self.speed_range[1]:
            errors.append("速度窗口下限大于上限")
        if self.max_time_s <= 0:
            errors.append("时间限制必须大于 0")
        if self.max_distance_m <= 0:
            errors.append("距离限制必须大于 0")
        for z in self.no_fly_zones:
            if z.radius_m <= 0:
                errors.append(f"禁飞区「{z.name}」半径必须大于 0")
        return errors

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "name": self.name,
            "description": self.description,
            "difficulty": self.difficulty,
            "home": [round(v, 7) for v in self.home],
            "required": [cp.to_dict() for cp in self.required],
            "altitude_range": [self.altitude_range[0], self.altitude_range[1]],
            "speed_range": [self.speed_range[0], self.speed_range[1]],
            "max_time_s": round(self.max_time_s, 1),
            "max_distance_m": round(self.max_distance_m, 1),
            "no_fly_zones": [z.to_dict() for z in self.no_fly_zones],
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskSpec:
        return cls(
            name=str(data.get("name", "航线规划考核任务")),
            description=str(data.get("description", "")),
            difficulty=str(data.get("difficulty", "easy")),
            home=tuple(float(v) for v in data.get("home", [31.20, 121.40, 0.0])),
            required=[CheckPoint.from_dict(d) for d in data.get("required", [])],
            altitude_range=tuple(float(v) for v in data.get("altitude_range", [50.0, 80.0])),
            speed_range=tuple(float(v) for v in data.get("speed_range", [8.0, 12.0])),
            max_time_s=float(data.get("max_time_s", 600.0)),
            max_distance_m=float(data.get("max_distance_m", 5000.0)),
            no_fly_zones=[Zone.from_dict(d) for d in data.get("no_fly_zones", [])],
        )

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")

    @classmethod
    def load(cls, path: str | Path) -> TaskSpec:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
