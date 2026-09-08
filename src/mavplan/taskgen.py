"""Deterministic task/route generator (v1.3 teaching suite).

``generate_task(seed, difficulty)`` produces a complete exam brief plus a
reference Mission (gold route) that satisfies every constraint of the brief
— instructors can hand out the brief to trainees and keep the gold route for
demo/grading snapshots.

Difficulty scaling:
  easy   : 3 required waypoints, no no-fly zone, wide windows
  medium : 4-5 required waypoints, 1 no-fly zone, medium windows, 1 area
  hard   : 6-7 required waypoints, 2-3 no-fly zones, tight windows, 1-2 areas

Geometry is generated with ``random.Random(seed)`` so the same seed always
reproduces the same brief. Placement rules keep every feature clear:

  - checkpoints / areas spread around the takeoff point;
  - no-fly zones keep a safety gap from checkpoints, home and each other;
  - no-fly zones additionally stay clear of every leg of the gold route
    (home -> points -> areas -> home), so the reference solution is always
    flyable and a trainee who follows the brief can score 100.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .mission import Mission
from .taskspec import TaskSpec, CheckPoint, Zone, haversine_m, _to_local_xy, _M_PER_DEG_LAT

# Difficulty presets -------------------------------------------------------
_DIFFICULTIES = {
    "easy": {
        "required_points": 3,
        "required_areas": 0,
        "no_fly_zones": 0,
        "radial_min_m": 300.0,
        "radial_max_m": 900.0,
        "checkpoint_radius_m": 25.0,
        "area_radius_m": 90.0,
        "zone_radius_m": (25.0, 60.0),
        "alt_range": (40.0, 90.0),
        "speed_range": (5.0, 15.0),
        "cruise_alt": 62.0,
        "cruise_speed": 10.0,
        "gap_m": 120.0,
        "segment_clear_m": 100.0,
        "time_factor": 1.45,
        "dist_factor": 1.30,
    },
    "medium": {
        "required_points": 4,
        "required_areas": 1,
        "no_fly_zones": 1,
        "radial_min_m": 300.0,
        "radial_max_m": 1200.0,
        "checkpoint_radius_m": 20.0,
        "area_radius_m": 80.0,
        "zone_radius_m": (30.0, 70.0),
        "alt_range": (50.0, 85.0),
        "speed_range": (7.0, 13.0),
        "cruise_alt": 66.0,
        "cruise_speed": 10.0,
        "gap_m": 150.0,
        "segment_clear_m": 110.0,
        "time_factor": 1.50,
        "dist_factor": 1.35,
    },
    "hard": {
        "required_points": 6,
        "required_areas": 2,
        "no_fly_zones": 3,
        "radial_min_m": 300.0,
        "radial_max_m": 1500.0,
        "checkpoint_radius_m": 15.0,
        "area_radius_m": 70.0,
        "zone_radius_m": (35.0, 80.0),
        "alt_range": (60.0, 78.0),
        "speed_range": (9.0, 12.0),
        "cruise_alt": 69.0,
        "cruise_speed": 10.0,
        "gap_m": 160.0,
        "segment_clear_m": 120.0,
        "time_factor": 1.55,
        "dist_factor": 1.40,
    },
}

_DIFF_NAMES = {"easy": "初级", "medium": "中级", "hard": "高级"}
_WP_NAMES = ["A", "B", "C", "D", "E", "F", "G", "H"]


@dataclass
class GeneratedTask:
    """A generated brief together with its gold reference route."""
    spec: TaskSpec
    gold_mission: Mission
    difficulty: str

    def save(self, spec_path: str, plan_path: str) -> None:
        self.spec.save(spec_path)
        self.gold_mission.save(plan_path)


def generate_task(
    seed: int,
    difficulty: str = "easy",
    name: str = "",
    description: str = "",
) -> GeneratedTask:
    """Generate a reproducible exam brief + gold route.

    Args:
        seed: Deterministic random seed.
        difficulty: easy / medium / hard.
        name: Optional task title (default: Chinese auto title).
        description: Optional mission text for trainees.

    Returns:
        GeneratedTask wrapping TaskSpec and reference Mission.
    """
    if difficulty not in _DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {sorted(_DIFFICULTIES)}")
    cfg = _DIFFICULTIES[difficulty]
    rng = random.Random(seed)

    # Training site drifts slightly around Shanghai (31.20N, 121.40E).
    home_lat = 31.20 + rng.uniform(-0.008, 0.008)
    home_lon = 121.40 + rng.uniform(-0.008, 0.008)
    home_alt = 0.0

    # -- required waypoints: spread angularly around home ----------------
    n_pts = cfg["required_points"]
    points: list[CheckPoint] = []
    for i in range(n_pts):
        angle = 2 * math.pi * i / n_pts + rng.uniform(-0.35, 0.35)
        radial = rng.uniform(cfg["radial_min_m"], cfg["radial_max_m"])
        lat, lon = _offset_latlon(home_lat, home_lon, angle, radial)
        points.append(CheckPoint(
            name=_WP_NAMES[i],
            lat=lat, lon=lon,
            radius_m=cfg["checkpoint_radius_m"],
            kind="point",
        ))

    # -- required areas ----------------------------------------------------
    areas: list[CheckPoint] = []
    for i in range(cfg["required_areas"]):
        pos = _place_clear_of(rng, home_lat, home_lon, points, areas, cfg, min_radius=cfg["area_radius_m"])
        if pos is None:
            break
        angle, radial = pos
        lat, lon = _offset_latlon(home_lat, home_lon, angle, radial)
        areas.append(CheckPoint(
            name=f"区域{i + 1}",
            lat=lat, lon=lon,
            radius_m=cfg["area_radius_m"],
            kind="area",
        ))

    # -- gold fly-through order (used both for the route and zone checks) --
    ordered_points = sorted(
        points, key=lambda cp: _bearing_deg(home_lat, home_lon, cp.lat, cp.lon)
    )
    ordered_cps = ordered_points + areas
    legs: list[tuple[float, float, float, float]] = []
    prev = (home_lat, home_lon)
    for cp in ordered_cps:
        legs.append((prev[0], prev[1], cp.lat, cp.lon))
        prev = (cp.lat, cp.lon)
    legs.append((prev[0], prev[1], home_lat, home_lon))

    # -- no-fly zones (kept clear of checkpoints AND of all route legs) ----
    zones: list[Zone] = []
    all_cps = points + areas
    for i in range(cfg["no_fly_zones"]):
        pos = _place_clear_of(rng, home_lat, home_lon, all_cps, zones, cfg,
                              min_radius=cfg["zone_radius_m"][1], legs=legs)
        if pos is None:
            break
        angle, radial = pos
        lat, lon = _offset_latlon(home_lat, home_lon, angle, radial)
        radius = rng.uniform(*cfg["zone_radius_m"])
        zones.append(Zone(name=f"禁飞区{i + 1}", lat=lat, lon=lon, radius_m=radius))

    # -- gold route --------------------------------------------------------
    gold = Mission(name=f"参考航线 seed={seed}", home=(home_lat, home_lon, home_alt))
    cruise_alt = cfg["cruise_alt"] + rng.uniform(-2.0, 2.0)
    cruise_speed = cfg["cruise_speed"] + rng.uniform(-0.5, 0.5)

    gold.add_waypoint(lat=home_lat, lon=home_lon, alt=0.0, speed=cruise_speed)
    for cp in ordered_cps:
        gold.add_waypoint(lat=cp.lat, lon=cp.lon, alt=cruise_alt, speed=cruise_speed)
    gold.add_waypoint(lat=home_lat, lon=home_lon, alt=0.0, speed=cruise_speed)

    total_dist = gold.total_distance()
    max_dist = total_dist * cfg["dist_factor"] + 300.0
    max_time = total_dist / cruise_speed * cfg["time_factor"] + 8.0 * len(gold) + 90.0

    if not name:
        name = f"航线规划考核·{_DIFF_NAMES[difficulty]}·seed {seed}"
    if not description:
        description = (
            f"从起飞点完成起飞，按自选顺序飞越全部必过航点，覆盖指定作业区域后返回降落。"
            f"巡航高度须保持在 {cfg['alt_range'][0]:.0f}~{cfg['alt_range'][1]:.0f}m，"
            f"速度 {cfg['speed_range'][0]:.0f}~{cfg['speed_range'][1]:.0f}m/s，"
            f"全程 {max_time / 60:.0f} 分钟内完成、航程不超过 {max_dist / 1000:.1f}km。"
            + ("航线不得进入禁飞区。" if zones else "本次无禁飞区。")
        )

    spec = TaskSpec(
        name=name,
        description=description,
        difficulty=difficulty,
        home=(home_lat, home_lon, home_alt),
        required=points + areas,
        altitude_range=cfg["alt_range"],
        speed_range=cfg["speed_range"],
        max_time_s=round(max_time, 1),
        max_distance_m=round(max_dist, 1),
        no_fly_zones=zones,
    )
    return GeneratedTask(spec=spec, gold_mission=gold, difficulty=difficulty)


# ------------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------------

def _offset_latlon(home_lat: float, home_lon: float, angle_rad: float, dist_m: float) -> tuple[float, float]:
    """Offset ``dist_m`` metres from home at ``angle_rad`` (0 = east)."""
    dx = math.cos(angle_rad) * dist_m
    dy = math.sin(angle_rad) * dist_m
    lat = home_lat + dy / _M_PER_DEG_LAT
    lon = home_lon + dx / (_M_PER_DEG_LAT * math.cos(math.radians(home_lat)))
    return lat, lon


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 in degrees."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _dist_point_to_segment_m(lat: float, lon: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Shortest distance from point to a segment, computed in local ENU.

    ``ax/ay/bx/by`` are the segment endpoints in local ENU metres around the
    point (i.e. the caller projects each endpoint relative to the point).
    """
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)
    t = -(ax * dx + ay * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px = ax + t * dx
    py = ay + t * dy
    return math.hypot(px, py)


def _clear_of_legs_m(lat: float, lon: float, legs, required_clear_m: float) -> bool:
    """True when the point keeps ``required_clear_m`` from every route leg."""
    for ax, ay, bx, by in legs:
        a = _to_local_xy(ax, ay, lat, lon)
        b = _to_local_xy(bx, by, lat, lon)
        if _dist_point_to_segment_m(lat, lon, a[0], a[1], b[0], b[1]) < required_clear_m:
            return False
    return True


def _place_clear_of(
    rng: random.Random,
    home_lat: float, home_lon: float,
    existing_pts: list,
    existing_zones: list,
    cfg: dict,
    min_radius: float,
    legs=None,
):
    """Pick (angle, radial) far from home, checkpoints, zones (and route legs)."""
    radial_min = cfg["radial_min_m"]
    radial_max = cfg["radial_max_m"]
    gap = cfg["gap_m"]
    for _attempt in range(120):
        angle = rng.uniform(0.0, 2 * math.pi)
        radial = rng.uniform(radial_min, radial_max)
        lat, lon = _offset_latlon(home_lat, home_lon, angle, radial)
        ok = True
        for cp in existing_pts:
            if haversine_m(lat, lon, cp.lat, cp.lon) < cp.radius_m + gap:
                ok = False
                break
        if not ok:
            continue
        for z in existing_zones:
            if haversine_m(lat, lon, z.lat, z.lon) < z.radius_m + gap:
                ok = False
                break
        if not ok:
            continue
        if haversine_m(lat, lon, home_lat, home_lon) < 150.0:
            continue  # keep clear of the takeoff area
        if legs is not None and not _clear_of_legs_m(lat, lon, legs, cfg["segment_clear_m"]):
            continue
        return angle, radial
    return None
