"""No-fly zone loading and mission preflight checks (v1.4 safety suite).

Preflight turns a planned mission into a structured warning list used by
``mavplan mission check`` and embedded into the v1.3 score report. Zones
are circles or polygons; KML import (already in the project) is reused so
an instructor can draw no-fly areas in Google Earth and check against
them directly.

Check categories (codes):
  - ``max_distance``    waypoint farther from home than the limit
  - ``max_altitude``    waypoint above the ceiling
  - ``no_fly_enter``    a route leg actually enters a zone (error)
  - ``no_fly_touch``    a route leg only grazes the zone boundary (tangent)
  - ``turn_radius``     required turning space below the aircraft minimum
  - ``bank_angle``      required bank ("slope") angle above the limit
  - ``battery_energy``  energy estimation says the flight is infeasible
  - ``battery_reserve`` remaining battery below the reserve margin

Every check item is a flat dict::

    {"code": "no_fly_enter", "level": "error",
     "message": "航段 WP3-WP4 进入禁飞区「跑道」",
     "waypoint": 3}            # optional context

Boundary semantics match the grading engine: a tangent path is NOT an
entry, but the preflight still reports it as ``no_fly_touch`` so trainees
see how close their route came to a protected area.
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .mission import Mission
from .simulate import BatteryModel, SimulationParams, estimate_energy
from .taskspec import Zone, point_in_polygon, segment_intersects_polygon

_G = 9.81
_M_PER_DEG_LAT = 111_320.0
# Distance (m) under which a near-miss counts as a tangent contact.
_TANGENT_EPS_M = 0.5

# Default teaching limits follow the VLOS rules already used by simulate
# (120 m ceiling / 500 m range). CLI flags can override for BVLOS briefs.
DEFAULT_MAX_ALTITUDE_M = 120.0
DEFAULT_MAX_DISTANCE_M = 500.0


# ----------------------------------------------------------------------
# Small geometry helpers (local equirectangular ENU, km-scale accurate)
# ----------------------------------------------------------------------

def _local(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """(east, north) offset in metres from point 1 to point 2."""
    x = (lon2 - lon1) * _M_PER_DEG_LAT * math.cos(math.radians(lat1))
    y = (lat2 - lat1) * _M_PER_DEG_LAT
    return x, y


def _distance_point_to_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float,
) -> float:
    """Shortest distance from point (px, py) to segment ab (metres)."""
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = -((ax - px) * dx + (ay - py) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _segment_distance_metres(
    lat1: float, lon1: float, lat2: float, lon2: float,
    lat3: float, lon3: float, lat4: float, lon4: float,
) -> float:
    """Shortest distance between two geodesic segments (ENU approx)."""
    ax, ay = 0.0, 0.0
    bx, by = _local(lat1, lon1, lat2, lon2)
    c = _local(lat1, lon1, lat3, lon3)
    dx, dy = _local(lat1, lon1, lat4, lon4)

    # Endpoint-to-other-segment distances bound the min distance.
    best = min(
        _distance_point_to_segment(c[0], c[1], ax, ay, bx, by),
        _distance_point_to_segment(dx, dy, ax, ay, bx, by),
        _distance_point_to_segment(ax, ay, c[0], c[1], dx, dy),
        _distance_point_to_segment(bx, by, c[0], c[1], dx, dy),
    )
    return best


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing in degrees [0, 360)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _heading_change_deg(b1: float, b2: float) -> float:
    """Smallest signed heading change from b1 to b2, in [0, 180]."""
    diff = (b2 - b1 + 540.0) % 360.0 - 180.0
    return abs(diff)


# ----------------------------------------------------------------------
# Zone loading (reuses the KML import family)
# ----------------------------------------------------------------------

def load_zones_from_kml(path: str | Path, circle_radius_m: float = 50.0) -> list[Zone]:
    """Read no-fly zones from a KML file.

    Every ``<Placemark>`` with a Polygon contributes a polygon zone (outer
    ring vertices); every Placemark with a Point contributes a circular
    zone of ``circle_radius_m``. Names come from the Placemark names.

    Args:
        path: KML file path.
        circle_radius_m: Radius for Point placemarks (polygons ignore it).

    Returns:
        List of Zone objects.

    Raises:
        ValueError: When the file cannot be parsed or no zone geometry found.
    """
    p = Path(path)
    if not p.exists():
        raise ValueError(f"File not found: {p}")
    try:
        root = ET.fromstring(p.read_text(encoding="utf-8", errors="replace"))
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML/KML file: {e}")

    ns = {"k": "http://www.opengis.net/kml/2.2"}
    zones: list[Zone] = []
    parent_map = {child: parent for parent in root.iter() for child in parent}

    def geom_kind(elem) -> str:
        """Nearest ancestor-or-self geometry tag: Polygon | Point | ''."""
        cur = elem
        while cur is not None:
            t = cur.tag.rsplit("}", 1)[-1]
            if t in ("Polygon", "Point"):
                return t
            cur = parent_map.get(cur)
        return ""

    for pm in root.iter():
        tag = pm.tag.rsplit("}", 1)[-1]
        if tag != "Placemark":
            continue
        name = ""
        for child in pm:
            ctag = child.tag.rsplit("}", 1)[-1]
            if ctag == "name" and child.text:
                name = child.text.strip()
                break
        for child in pm.iter():
            ctag = child.tag.rsplit("}", 1)[-1]
            if ctag == "coordinates":
                coords = _parse_kml_coordinates(child.text or "")
                if not coords:
                    continue
                gtag = geom_kind(child)
                if gtag == "Polygon" and len(coords) >= 3:
                    ring = [(la, lo) for la, lo, _ in coords]
                    if ring[0] == ring[-1]:
                        ring = ring[:-1]
                    zones.append(Zone(
                        name=name or "禁飞区(多边形)",
                        lat=ring[0][0], lon=ring[0][1],
                        kind="polygon", vertices=ring,
                    ))
                elif gtag == "Point":
                    la, lo, _ = coords[0]
                    zones.append(Zone(
                        name=name or "禁飞区",
                        lat=la, lon=lo, radius_m=circle_radius_m,
                        kind="circle",
                    ))
    if not zones:
        raise ValueError(f"No Polygon/Point no-fly geometry found in KML: {p}")
    return zones


def _parse_kml_coordinates(text: str) -> list[tuple[float, float, float]]:
    """Parse 'lon,lat,alt lon,lat,alt ...' text."""
    out: list[tuple[float, float, float]] = []
    for tok in text.split():
        parts = tok.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            out.append((float(parts[1]), float(parts[0]),
                        float(parts[2]) if len(parts) >= 3 else 0.0))
        except ValueError:
            continue
    return out


def load_zones_json(path: str | Path) -> list[Zone]:
    """Load zones from a JSON file.

    Accepted layouts: a bare list of zone dicts, ``{"zones": [...]}`` or a
    single zone dict. Each zone follows ``Zone.to_dict()`` (kind circle or
    polygon). Invalid entries raise ValueError.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "zones" in data:
        data = data["zones"]
    if isinstance(data, dict):
        data = [data]
    zones = [Zone.from_dict(item) for item in data]
    for z in zones:
        errs = z.validate()
        if errs:
            raise ValueError(f"Invalid zone in {path}: {'; '.join(errs)}")
    return zones


# ----------------------------------------------------------------------
# Preflight engine
# ----------------------------------------------------------------------

@dataclass
class PreflightParams:
    """Limits and aircraft parameters used by :func:`preflight_check`."""
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M   # from home
    max_altitude_m: float = DEFAULT_MAX_ALTITUDE_M
    cruise_speed: float = 10.0      # m/s, fallback when waypoint has no speed
    bank_deg: float = 35.0          # max bank / "slope" angle for turns
    battery: BatteryModel = field(default_factory=BatteryModel)
    reserve_percent: float = 20.0


def preflight_check(
    mission: Mission,
    zones: list[Zone] | None = None,
    params: PreflightParams | None = None,
) -> list[dict]:
    """Run all safety checks on ``mission``.

    Args:
        mission: Planned Mission to validate.
        zones: No-fly zones (circle/polygon). Empty list skips zone checks.
        params: Limits (defaults are VLOS teaching values).

    Returns:
        Structured warning list (flat dicts, see module docstring), sorted
        from most severe to least (error -> warning -> info).
    """
    p = params or PreflightParams()
    zones = zones or []
    items: list[dict] = []
    wps = mission.waypoints()
    if not wps:
        return [{"code": "empty_mission", "level": "error",
                 "message": "任务为空，无法预检"}]
    home = wps[0]

    # ---- max distance / max altitude -----------------------------------
    for wp in wps:
        dist = _local(home.lat, home.lon, wp.lat, wp.lon)
        range_m = math.hypot(dist[0], dist[1])
        if range_m > p.max_distance_m:
            items.append({
                "code": "max_distance",
                "level": "error",
                "waypoint": wp.seq,
                "message": (
                    f"WP{wp.seq} 距起降点 {range_m/1000:.2f} km，超过最大允许距离 "
                    f"{p.max_distance_m/1000:.1f} km"
                ),
            })
        if wp.alt > p.max_altitude_m:
            items.append({
                "code": "max_altitude",
                "level": "error",
                "waypoint": wp.seq,
                "message": (
                    f"WP{wp.seq} 高度 {wp.alt:.0f} m，超过最大允许高度 {p.max_altitude_m:.0f} m"
                ),
            })

    # ---- no-fly zone intersection --------------------------------------
    rel_scores = {"clear": 0, "touch": 1, "enter": 2}
    for zone in zones:
        relation = "clear"
        where = ""
        for i in range(len(wps) - 1):
            a, b = wps[i], wps[i + 1]
            rel = _segment_zone_relation(zone, a.lat, a.lon, b.lat, b.lon)
            if rel_scores.get(rel, 0) > rel_scores.get(relation, 0):
                relation = rel
                where = f"WP{a.seq}-WP{b.seq}"
        if relation == "enter":
            items.append({
                "code": "no_fly_enter",
                "level": "error",
                "message": f"航段 {where} 进入禁飞区「{zone.name}」({zone.shape_label()})",
            })
        elif relation == "touch":
            items.append({
                "code": "no_fly_touch",
                "level": "warning",
                "message": (
                    f"航段 {where} 与禁飞区「{zone.name}」({zone.shape_label()}) 边界相切/"
                    f"擦边，建议保持安全距离"
                ),
            })

    # ---- turn radius / bank (slope) ------------------------------------
    for i in range(1, len(wps) - 1):
        prev, cur, nxt = wps[i - 1], wps[i], wps[i + 1]
        seg1 = prev.distance_to(cur)
        seg2 = cur.distance_to(nxt)
        if seg1 < 1e-6 or seg2 < 1e-6:
            continue
        turn_deg = _heading_change_deg(
            _bearing_deg(prev.lat, prev.lon, cur.lat, cur.lon),
            _bearing_deg(cur.lat, cur.lon, nxt.lat, nxt.lon),
        )
        if turn_deg < 3.0:
            continue
        v = cur.speed if cur.speed and cur.speed > 0 else p.cruise_speed
        theta = math.radians(turn_deg)
        chord = min(seg1, seg2)
        r_geom = chord / (2.0 * math.sin(theta / 2.0)) if theta > 0 else float("inf")
        r_min = (v * v) / (_G * math.tan(math.radians(p.bank_deg)))
        if r_geom < r_min - 0.5:
            items.append({
                "code": "turn_radius",
                "level": "error",
                "waypoint": cur.seq,
                "message": (
                    f"WP{cur.seq} 转弯角 {turn_deg:.0f}°、可用转弯半径约 {r_geom:.0f} m，"
                    f"小于最小转弯半径 {r_min:.0f} m（速度 {v:.1f} m/s、最大坡度 "
                    f"{p.bank_deg:.0f}°）"
                ),
            })
        if r_geom > 0:
            bank_req = math.degrees(math.atan((v * v) / (_G * r_geom)))
            if bank_req > p.bank_deg + 0.5:
                items.append({
                    "code": "bank_angle",
                    "level": "warning",
                    "waypoint": cur.seq,
                    "message": (
                        f"WP{cur.seq} 转弯需坡度约 {bank_req:.0f}°，超过最大坡度限制 "
                        f"{p.bank_deg:.0f}°（教学规则：坡度不应超出机动包线）"
                    ),
                })

    # ---- battery margin ------------------------------------------------
    sim_params = SimulationParams(battery=p.battery, reserve_percent=p.reserve_percent)
    result = estimate_energy(mission, sim_params)
    if result.total_distance_m > 0 and not result.feasible:
        items.append({
            "code": "battery_energy",
            "level": "error",
            "message": (
                f"电池余量不足：预计消耗 {result.energy_consumed_wh:.0f} Wh "
                f"(容量 {result.energy_total_wh:.0f} Wh, {result.battery_used_percent:.0f}%)，"
                f"任务不可执行"
            ),
        })
    elif result.total_distance_m > 0 and result.battery_remaining_percent < p.reserve_percent:
        items.append({
            "code": "battery_reserve",
            "level": "warning",
            "message": (
                f"电池余量偏紧：预计剩余 {result.battery_remaining_percent:.0f}%"
                f"（要求保留 {p.reserve_percent:.0f}% 安全余量）"
            ),
        })

    items.sort(key=lambda it: _severity_rank(it["level"]), reverse=True)
    return items


def _severity_rank(level: str) -> int:
    return {"error": 3, "warning": 2, "info": 1}.get(level, 0)


def _segment_zone_relation(zone: Zone, lat1: float, lon1: float,
                           lat2: float, lon2: float) -> str:
    """Classify a route leg against one zone: 'enter'|'touch'|'clear'.

    - circle:  compare the segment's closest approach to the radius
    - polygon: strict-entry helpers first, then boundary distance
    A pure tangent is never 'enter' (matches grading), but it is 'touch'.
    """
    eps = _TANGENT_EPS_M
    if zone.kind == "circle":
        c = zone
        ax, ay = _local(c.lat, c.lon, lat1, lon1)
        bx, by = _local(c.lat, c.lon, lat2, lon2)
        # distance from circle centre (origin) to segment, clamped.
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            dist = math.hypot(ax, ay)
        else:
            t = -(ax * dx + ay * dy) / (dx * dx + dy * dy)
            t = max(0.0, min(1.0, t))
            dist = math.hypot(ax + t * dx, ay + t * dy)
        if dist < zone.radius_m - eps:
            return "enter"
        if dist <= zone.radius_m + eps:
            return "touch"
        return "clear"

    ring = zone.polygon_ring()
    if len(ring) < 3:
        return "clear"
    if point_in_polygon(lat1, lon1, ring) or point_in_polygon(lat2, lon2, ring):
        return "enter"
    if segment_intersects_polygon(lat1, lon1, lat2, lon2, ring):
        return "enter"
    # distance from the route leg to the polygon boundary
    best = float("inf")
    for i in range(len(ring)):
        a = ring[i]
        b = ring[(i + 1) % len(ring)]
        d = _segment_distance_metres(lat1, lon1, lat2, lon2,
                                     a[0], a[1], b[0], b[1])
        best = min(best, d)
    if best <= eps:
        return "touch"
    return "clear"


def preflight_summary(items: list[dict]) -> dict:
    """Counts per level: {'errors': n, 'warnings': n, 'info': n}."""
    return {
        "errors": sum(1 for it in items if it["level"] == "error"),
        "warnings": sum(1 for it in items if it["level"] == "warning"),
        "info": sum(1 for it in items if it["level"] == "info"),
    }
