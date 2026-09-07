"""Automated mission pattern generators: lawn-mower, polygon scan, orbit."""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Literal

from .waypoint import Waypoint


# ------------------------------------------------------------------
# Internal geometry helpers
# ------------------------------------------------------------------

# Earth radius in metres (WGS84 mean)
_EARTH_R = 6_371_000.0


def _m_to_deg_lat(m: float) -> float:
    return math.degrees(m / _EARTH_R)


def _m_to_deg_lon(m: float, lat: float) -> float:
    """Convert metres to degrees longitude, at given latitude."""
    return math.degrees(m / (_EARTH_R * math.cos(math.radians(lat))))


def _deg_lat_to_m(deg: float) -> float:
    return _EARTH_R * math.abs(math.radians(deg))


def _deg_lon_to_m(deg: float, lat: float) -> float:
    cp = math.cos(math.radians(lat))
    if cp < 1e-10:
        return float("inf")
    return _EARTH_R * cp * math.abs(math.radians(deg))


# ------------------------------------------------------------------
# Enums / dataclasses
# ------------------------------------------------------------------

class StartCorner(Enum):
    NW = "nw"  # Start at north-west corner, sweep east
    NE = "ne"  # Start at north-east corner, sweep west
    SW = "sw"  # Start at south-west corner, sweep east
    SE = "se"  # Start at south-east corner, sweep west

    @classmethod
    def from_str(cls, s: str) -> StartCorner:
        return cls(s.lower())


class SweepDirection(Enum):
    EW = "ew"  # East-to-West sweep (lawn-mower rows go east→west)
    WE = "we"  # West-to-East sweep


@dataclass
class LawnMowerParams:
    """Parameters for the rectangular lawn-mower (survey) pattern.

    Attributes:
        corner1, corner2: Two opposite corners of the survey rectangle.
            Each is a (lat, lon) tuple in degrees.
        altitude: Survey altitude in metres (relative altitude).
        speed: Cruise speed in m/s.
        lane_spacing: Spacing between parallel survey lanes in metres.
        start_corner: Which corner to start from (NW/NE/SW/SE).
        start_from_outer: If True, start from the outer edge of the area
            (recommended for minimum battery climb-out distance).
        roi_lat, roi_lon: Optional Region of Interest camera target
            (camera always points here while flying). If None, yaw is
            unconstrained (-9999).
    """

    corner1: tuple[float, float]
    corner2: tuple[float, float]
    altitude: float
    speed: float = 10.0
    lane_spacing: float = 20.0
    start_corner: StartCorner = StartCorner.NW
    start_from_outer: bool = True
    roi_lat: float | None = None
    roi_lon: float | None = None

    def validate(self) -> list[str]:
        errors = []
        lat1, lon1 = self.corner1
        lat2, lon2 = self.corner2
        if not (-90 <= lat1 <= 90) or not (-90 <= lat2 <= 90):
            errors.append("Latitude values must be in range -90 to 90")
        if not (-180 <= lon1 <= 180) or not (-180 <= lon2 <= 180):
            errors.append("Longitude values must be in range -180 to 180")
        if self.lane_spacing <= 0:
            errors.append("lane_spacing must be positive")
        if self.altitude < 0:
            errors.append("altitude must be non-negative")
        if self.speed <= 0:
            errors.append("speed must be positive")
        if abs(lat1 - lat2) < 1e-9 or abs(lon1 - lon2) < 1e-9:
            errors.append("corner1 and corner2 must be different points")
        return errors


@dataclass
class PolygonScanParams:
    """Parameters for the polygon-area lawn-mower scan.

    Attributes:
        polygon: List of (lat, lon) vertices defining the survey area
            (clockwise or counter-clockwise, closed polygon).
        altitude: Survey altitude in metres.
        speed: Cruise speed in m/s.
        lane_spacing: Spacing between parallel survey lanes in metres.
        sweep_angle_deg: Compass bearing of the primary survey lanes
            (0=North, 90=East). Default 0 (north-south lanes, fly east-west).
        start_from_outer: If True, start from the edge closest to corner1.
    """

    polygon: list[tuple[float, float]]
    altitude: float
    speed: float = 10.0
    lane_spacing: float = 20.0
    sweep_angle_deg: float = 0.0
    start_from_outer: bool = True
    roi_lat: float | None = None
    roi_lon: float | None = None

    def validate(self) -> list[str]:
        errors = []
        if len(self.polygon) < 3:
            errors.append("Polygon must have at least 3 vertices")
        for i, (lat, lon) in enumerate(self.polygon):
            if not (-90 <= lat <= 90):
                errors.append(f"Vertex {i}: latitude {lat} out of range")
            if not (-180 <= lon <= 180):
                errors.append(f"Vertex {i}: longitude {lon} out of range")
        if self.lane_spacing <= 0:
            errors.append("lane_spacing must be positive")
        if self.speed <= 0:
            errors.append("speed must be positive")
        return errors


@dataclass
class OrbitParams:
    """Parameters for a circular orbit / loiter pattern.

    Attributes:
        center_lat, center_lon: Circle centre in degrees.
        radius: Orbit radius in metres.
        altitude: Orbit altitude in metres.
        speed: Orbit speed in m/s.
        num_points: Number of waypoints around the circle.
        direction: "cw" (clockwise) or "ccw" (counter-clockwise).
        start_bearing_deg: Compass bearing of the first waypoint (0=North).
    """

    center_lat: float
    center_lon: float
    radius: float
    altitude: float
    speed: float = 10.0
    num_points: int = 12
    direction: Literal["cw", "ccw"] = "ccw"
    start_bearing_deg: float = 0.0

    def validate(self) -> list[str]:
        errors = []
        if not -90 <= self.center_lat <= 90:
            errors.append("center_lat must be in range -90 to 90")
        if not -180 <= self.center_lon <= 180:
            errors.append("center_lon must be in range -180 to 180")
        if self.radius <= 0:
            errors.append("radius must be positive")
        if self.altitude < 0:
            errors.append("altitude must be non-negative")
        if self.speed <= 0:
            errors.append("speed must be positive")
        if self.num_points < 3:
            errors.append("num_points must be at least 3")
        return errors


# ------------------------------------------------------------------
# Core pattern generators
# ------------------------------------------------------------------

def generate_lawnmower(params: LawnMowerParams) -> Iterator[Waypoint]:
    """Generate waypoints for a rectangular lawn-mower (sector) pattern.

    The pattern produces parallel tracks across a rectangular area in a
    back-and-forth (lawn-mower) manner, similar to how a lawn is mowed.

    Args:
        params: LawnMowerParams describing the area and pattern options.

    Yields:
        Waypoint objects in flight order.
    """
    errors = params.validate()
    if errors:
        raise ValueError("Invalid lawn-mower params: " + "; ".join(errors))

    lat1, lon1 = params.corner1
    lat2, lon2 = params.corner2

    # Bounding rectangle
    min_lat = min(lat1, lat2)
    max_lat = max(lat1, lat2)
    min_lon = min(lon1, lon2)
    max_lon = max(lon1, lon2)

    # Lane spacing in degrees (at the average latitude)
    avg_lat = (min_lat + max_lat) / 2.0
    d_lat = _m_to_deg_lat(params.lane_spacing)
    d_lon = _m_to_deg_lon(params.lane_spacing, avg_lat)

    # Number of complete lanes
    lat_range = max_lat - min_lat
    num_full_lanes = max(1, int(lat_range / d_lat))
    # Adjust d_lat so lanes are evenly spaced across the full range
    d_lat = lat_range / num_full_lanes if num_full_lanes > 0 else 0

    # Determine row order based on start_corner
    # Rows go from north to south (lat decreasing)
    row_lats = [max_lat - i * d_lat for i in range(num_full_lanes + 1)]

    # Sweep direction for each row (alternate)
    # Start from outer edge if requested (outermost row first)
    if params.start_from_outer:
        row_lats = list(reversed(row_lats))

    for i, row_lat in enumerate(row_lats):
        # Clip row to bounding longitude
        row_lat = max(min_lat, min(max_lat, row_lat))
        # Even rows: west→east, odd rows: east→west
        sweep_east = (i % 2 == 0)
        if params.start_corner in (StartCorner.NE, StartCorner.SE):
            sweep_east = not sweep_east

        wp = Waypoint(
            lat=row_lat,
            lon=min_lon if sweep_east else max_lon,
            alt=params.altitude,
            speed=params.speed,
            yaw=-9999 if params.roi_lat is None else _bearing_to(
                row_lat, min_lon if sweep_east else max_lon,
                params.roi_lat, params.roi_lon
            ),
        )
        yield wp

        wp2 = Waypoint(
            lat=row_lat,
            lon=max_lon if sweep_east else min_lon,
            alt=params.altitude,
            speed=params.speed,
            yaw=-9999 if params.roi_lat is None else _bearing_to(
                row_lat, max_lon if sweep_east else min_lon,
                params.roi_lat, params.roi_lon
            ),
        )
        yield wp2


def generate_polygon_scan(params: PolygonScanParams) -> Iterator[Waypoint]:
    """Generate waypoints for a lawn-mower scan within a polygon area.

    A bounding box is computed from the polygon vertices, and the
    standard lawn-mower pattern is clipped to the polygon interior.
    Waypoints that fall outside the polygon are skipped.

    Args:
        params: PolygonScanParams describing the area and pattern options.

    Yields:
        Waypoint objects that fall within the polygon.
    """
    errors = params.validate()
    if errors:
        raise ValueError("Invalid polygon scan params: " + "; ".join(errors))

    polygon = params.polygon

    # Bounding box
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    min_lat = min(lats)
    max_lat = max(lats)
    min_lon = min(lons)
    max_lon = max(lons)

    avg_lat = (min_lat + max_lat) / 2.0
    d_lat = _m_to_deg_lat(params.lane_spacing)
    lat_range = max_lat - min_lat
    num_lanes = max(1, int(lat_range / d_lat))
    d_lat = lat_range / num_lanes if num_lanes > 0 else 0

    row_lats = [max_lat - i * d_lat for i in range(num_lanes + 1)]
    if params.start_from_outer:
        row_lats = list(reversed(row_lats))

    for i, row_lat in enumerate(row_lats):
        row_lat = max(min_lat, min(max_lat, row_lat))
        sweep_east = (i % 2 == 0)
        p1_lat, p1_lon = row_lat, min_lon
        p2_lat, p2_lon = row_lat, max_lon

        for wp_lat, wp_lon in _intersect_segment_with_polygon(
            p1_lat, p1_lon, p2_lat, p2_lon, polygon
        ):
            wp = Waypoint(
                lat=wp_lat,
                lon=wp_lon,
                alt=params.altitude,
                speed=params.speed,
                yaw=-9999,
            )
            yield wp


def generate_orbit(params: OrbitParams) -> Iterator[Waypoint]:
    """Generate waypoints for a circular orbit / loiter pattern.

    Args:
        params: OrbitParams describing the circle.

    Yields:
        Waypoint objects around the circle in order.
    """
    errors = params.validate()
    if errors:
        raise ValueError("Invalid orbit params: " + "; ".join(errors))

    step = 360.0 / params.num_points
    sign = -1 if params.direction == "cw" else 1

    for i in range(params.num_points):
        bearing = (params.start_bearing_deg + sign * i * step) % 360
        lat, lon = _destination(params.center_lat, params.center_lon,
                                params.radius, bearing)
        wp = Waypoint(
            lat=lat,
            lon=lon,
            alt=params.altitude,
            speed=params.speed,
            yaw=bearing,
        )
        yield wp


# ------------------------------------------------------------------
# Geometric utility functions
# ------------------------------------------------------------------

def _bearing_to(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing (0-360) from (lat1,lon1) to (lat2,lon2)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def _destination(lat: float, lon: float, dist_m: float, bearing_deg: float) -> tuple[float, float]:
    """Compute destination point given start, distance, and bearing.

    Returns (lat, lon) in degrees.
    """
    R = _EARTH_R
    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    theta = math.radians(bearing_deg)

    delta = dist_m / R
    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2)
    )
    return math.degrees(phi2), (math.degrees(lam2) + 540) % 360 - 180


def _point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]
        if ((lon_i > lon) != (lon_j > lon)) and \
           lat < (lat_j - lat_i) * (lon - lon_i) / (lon_j - lon_i) + lat_i:
            inside = not inside
        j = i
    return inside


def _line_segment_intersection(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float
) -> list[tuple[float, float]]:
    """Return intersection points of segment AB with segment CD.

    For the polygon scan: intersects a horizontal scan line (row at
    constant lat) with polygon edges.
    """
    results = []

    denom = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
    if abs(denom) < 1e-12:
        return results  # Parallel or coincident

    t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / denom
    u = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / denom

    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        ix = ax + t * (bx - ax)
        iy = ay + t * (by - ay)
        results.append((iy, ix))  # lat, lon order
    return results


def _intersect_segment_with_polygon(
    lat1: float, lon1: float, lat2: float, lon2: float,
    polygon: list[tuple[float, float]]
) -> Iterator[tuple[float, float]]:
    """Yield intersection points of a segment with polygon edges, sorted by lon."""
    points = []
    n = len(polygon)
    for i in range(n):
        p_lat, p_lon = polygon[i]
        q_lat, q_lon = polygon[(i + 1) % n]
        hits = _line_segment_intersection(lon1, lat1, lon2, lat2, p_lon, p_lat, q_lon, q_lat)
        for hit_lat, hit_lon in hits:
            # Only include if within the scan segment's lon range
            min_lon_s = min(lon1, lon2) - 1e-10
            max_lon_s = max(lon1, lon2) + 1e-10
            if min_lon_s <= hit_lon <= max_lon_s:
                # Also verify point is inside polygon (floating point safety)
                if _point_in_polygon(hit_lat, hit_lon, polygon):
                    points.append((hit_lat, hit_lon))
    # Sort by longitude
    points.sort(key=lambda p: p[1])
    yield from points
