"""Mission simulation: battery estimation, wind effects, safety checks.

Provides:
  - Battery consumption model
  - Wind adjustment for flight time
  - Automatic takeoff/landing/RTL waypoint insertion
  - Geofence distance check (max range from home)
  - Simulation report generation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .mission import Mission
from .waypoint import Waypoint


# ------------------------------------------------------------------
# Enums
# ------------------------------------------------------------------

class WindDirection(Enum):
    HEADWIND = "headwind"      # Against travel direction, slows down
    TAILWIND = "tailwind"      # With travel direction, speeds up
    CROSSWIND = "crosswind"    # Perpendicular, no speed change
    NONE = "none"


# ------------------------------------------------------------------
# Dataclasses
# ------------------------------------------------------------------

@dataclass
class BatteryModel:
    """Battery specification for energy estimation.

    Attributes:
        capacity_mah: Battery capacity in milliampere-hours.
        hover_current_ma: Current draw at hover (no movement).
        cruise_current_ma: Current draw at cruise speed.
        voltage: Nominal cell voltage (e.g. 3.7V for LiPo cell, 22.2V for 6S).
        num_cells: Number of cells in series (1S, 2S, ... 6S).
    """
    capacity_mah: float = 5000.0
    hover_current_ma: float = 20000.0   # 20A at hover
    cruise_current_ma: float = 25000.0  # 25A at cruise
    voltage: float = 22.2               # 6S LiPo
    num_cells: int = 6

    @property
    def capacity_wh(self) -> float:
        """Battery energy capacity in watt-hours."""
        return self.capacity_mah / 1000.0 * self.voltage

    @property
    def hover_power_w(self) -> float:
        return self.hover_current_ma / 1000.0 * self.voltage

    @property
    def cruise_power_w(self) -> float:
        return self.cruise_current_ma / 1000.0 * self.voltage


@dataclass
class WindModel:
    """Wind conditions for flight time adjustment.

    Attributes:
        speed_ms: Wind speed in m/s.
        direction: Relative to travel direction (head/tail/cross).
    """
    speed_ms: float = 0.0
    direction: WindDirection = WindDirection.NONE

    def speed_factor(self) -> float:
        """Effective speed multiplier due to wind.

        Returns a factor < 1.0 for headwind (slower), > 1.0 for tailwind.
        For cruising, wind reduces ground speed by approximately
        wind_speed / cruise_speed in the headwind case.
        """
        if self.speed_ms <= 0:
            return 1.0
        # Assume cruise speed ~ 10 m/s nominal
        nominal_cruise = 10.0
        ratio = self.speed_ms / nominal_cruise
        if self.direction == WindDirection.HEADWIND:
            return max(0.3, 1.0 - ratio * 0.8)
        elif self.direction == WindDirection.TAILWIND:
            return min(1.8, 1.0 + ratio * 0.5)
        else:
            return 1.0  # crosswind or none: no ground speed change


@dataclass
class SimulationParams:
    """Parameters for mission simulation."""
    battery: BatteryModel = field(default_factory=BatteryModel)
    wind: WindModel = field(default_factory=WindModel)
    cruise_speed: float = 10.0       # m/s
    takeoff_speed: float = 3.0       # m/s vertical
    landing_speed: float = 2.0       # m/s vertical
    takeoff_altitude: float = 50.0   # m above home
    reserve_percent: float = 20.0    # battery reserve to keep
    payload_weight_kg: float = 1.0   # for future expansion


@dataclass
class SimulationResult:
    """Result of mission simulation."""
    total_distance_m: float
    total_time_s: float
    hover_time_s: float
    cruise_time_s: float
    energy_consumed_wh: float
    energy_total_wh: float
    battery_used_percent: float
    battery_remaining_percent: float
    feasible: bool
    warnings: list[str] = field(default_factory=list)
    max_range_from_home_m: float = 0.0
    max_altitude_m: float = 0.0


# ------------------------------------------------------------------
# Core simulation logic
# ------------------------------------------------------------------

def estimate_energy(mission: Mission, params: SimulationParams) -> SimulationResult:
    """Estimate flight time and battery consumption for a mission.

    Args:
        mission: Planned Mission with waypoints.
        params: SimulationParams (battery, wind, speeds).

    Returns:
        SimulationResult with time/energy estimates and feasibility.
    """
    warnings: list[str] = []
    wps = mission.waypoints()

    if len(wps) < 2:
        warnings.append("Mission has fewer than 2 waypoints; simulation incomplete")
        return SimulationResult(
            total_distance_m=0, total_time_s=0, hover_time_s=0, cruise_time_s=0,
            energy_consumed_wh=0, energy_total_wh=params.battery.capacity_wh,
            battery_used_percent=0, battery_remaining_percent=100, feasible=False,
            warnings=warnings,
        )

    wind_factor = params.wind.speed_factor()
    effective_cruise = params.cruise_speed * wind_factor

    total_dist = 0.0
    cruise_time = 0.0
    hover_time = 0.0
    max_range = 0.0
    max_alt = 0.0

    home_lat = wps[0].lat
    home_lon = wps[0].lon

    for i in range(1, len(wps)):
        prev = wps[i - 1]
        curr = wps[i]
        seg_dist = prev.distance_to(curr)
        total_dist += seg_dist

        # Time for this segment
        if effective_cruise > 0:
            seg_time = seg_dist / effective_cruise
        else:
            seg_time = seg_dist / max(1.0, params.cruise_speed)
        cruise_time += seg_time

        # Hover time at waypoint (delay field)
        if curr.delay > 0:
            hover_time += curr.delay

        # Max range from home
        range_from_home = _haversine(home_lat, home_lon, curr.lat, curr.lon)
        max_range = max(max_range, range_from_home)

        # Max altitude
        max_alt = max(max_alt, curr.alt)

    # Add takeoff and landing time
    takeoff_time = params.takeoff_altitude / params.takeoff_speed
    landing_time = params.takeoff_altitude / params.landing_speed
    total_time = cruise_time + hover_time + takeoff_time + landing_time

    # Energy: cruise power * cruise_time + hover power * hover_time
    # Plus takeoff/landing at hover power (vertical movement)
    energy_cruise = params.battery.cruise_power_w * (cruise_time / 3600.0)
    energy_hover = params.battery.hover_power_w * ((hover_time + takeoff_time + landing_time) / 3600.0)
    energy_total = energy_cruise + energy_hover

    energy_capacity = params.battery.capacity_wh
    used_percent = (energy_total / energy_capacity) * 100.0 if energy_capacity > 0 else 0.0
    remaining_percent = 100.0 - used_percent - params.reserve_percent

    feasible = remaining_percent > 0

    if used_percent > 100:
        warnings.append(f"Battery insufficient: needs {used_percent:.0f}% of capacity")
    if remaining_percent < params.reserve_percent:
        warnings.append(f"Battery below reserve ({params.reserve_percent:.0f}%): only {remaining_percent:.0f}% left")

    if max_alt > 120:
        warnings.append(f"Max altitude {max_alt:.0f}m exceeds typical VLOS limit (120m)")

    if max_range > 500:
        warnings.append(f"Max range from home {max_range/1000:.1f}km exceeds typical VLOS (500m)")

    return SimulationResult(
        total_distance_m=total_dist,
        total_time_s=total_time,
        hover_time_s=hover_time + takeoff_time + landing_time,
        cruise_time_s=cruise_time,
        energy_consumed_wh=energy_total,
        energy_total_wh=energy_capacity,
        battery_used_percent=used_percent,
        battery_remaining_percent=remaining_percent,
        feasible=feasible,
        warnings=warnings,
        max_range_from_home_m=max_range,
        max_altitude_m=max_alt,
    )


def insert_takeoff_landing(mission: Mission, params: SimulationParams) -> Mission:
    """Insert takeoff and landing waypoints around the mission.

    Adds:
      - A takeoff waypoint at home position, climbing to takeoff_altitude
      - A landing/RTL waypoint returning to home at 0 altitude

    Args:
        mission: Original Mission.
        params: SimulationParams with takeoff_altitude.

    Returns:
        New Mission with takeoff/landing waypoints added.
    """
    if not mission.waypoints():
        return mission

    new_mission = Mission(name=mission.name + " (with TOL)")
    wps = mission.waypoints()

    # Takeoff from first waypoint position
    home = wps[0]
    new_mission.add_waypoint(
        lat=home.lat, lon=home.lon, alt=params.takeoff_altitude,
        speed=params.takeoff_speed, delay=0, yaw=home.yaw,
    )

    # Copy original waypoints
    for wp in wps:
        new_mission.add_waypoint(
            lat=wp.lat, lon=wp.lon, alt=wp.alt,
            speed=wp.speed if wp.speed > 0 else params.cruise_speed,
            delay=wp.delay, yaw=wp.yaw,
        )

    # Landing back at home
    new_mission.add_waypoint(
        lat=home.lat, lon=home.lon, alt=0.0,
        speed=params.landing_speed, delay=0, yaw=-9999,
    )

    return new_mission


def check_geofence(mission: Mission, max_range_m: float = 500.0) -> list[str]:
    """Check if all waypoints stay within a geofence radius from home.

    Args:
        mission: Mission to check.
        max_range_m: Maximum allowed distance from home (metres).

    Returns:
        List of warning strings (empty if all waypoints within fence).
    """
    warnings: list[str] = []
    wps = mission.waypoints()
    if not wps:
        return warnings

    home = wps[0]
    for wp in wps[1:]:
        dist = _haversine(home.lat, home.lon, wp.lat, wp.lon)
        if dist > max_range_m:
            warnings.append(
                f"Waypoint {wp.seq} at {dist/1000:.2f}km exceeds geofence "
                f"({max_range_m/1000:.1f}km from home)"
            )

    return warnings


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres."""
    import math
    R = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ------------------------------------------------------------------
# Report generation
# ------------------------------------------------------------------

def generate_report(mission: Mission, params: SimulationParams) -> str:
    """Generate a human-readable simulation report.

    Args:
        mission: Mission to simulate.
        params: SimulationParams.

    Returns:
        Multi-line report string.
    """
    result = estimate_energy(mission, params)
    geom_warnings = check_geofence(mission)

    lines = []
    lines.append("=" * 50)
    lines.append(f"  Mission Simulation Report: {mission.name}")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"  Battery: {params.battery.capacity_mah:.0f}mAh @ {params.battery.voltage:.1f}V "
                 f"({params.battery.capacity_wh:.0f}Wh)")
    lines.append(f"  Wind: {params.wind.speed_ms:.1f} m/s ({params.wind.direction.value})")
    lines.append("")
    lines.append(f"  Total distance: {result.total_distance_m/1000:.2f} km")
    lines.append(f"  Cruise time:    {result.cruise_time_s/60:.1f} min")
    lines.append(f"  Hover time:     {result.hover_time_s/60:.1f} min")
    lines.append(f"  Total time:     {result.total_time_s/60:.1f} min")
    lines.append("")
    lines.append(f"  Energy used:    {result.energy_consumed_wh:.1f} Wh "
                 f"({result.battery_used_percent:.0f}% of capacity)")
    lines.append(f"  Battery left:   {result.battery_remaining_percent:.0f}% "
                 f"(after {params.reserve_percent:.0f}% reserve)")
    lines.append(f"  Max range:      {result.max_range_from_home_m/1000:.2f} km from home")
    lines.append(f"  Max altitude:   {result.max_altitude_m:.0f} m")
    lines.append("")
    if result.feasible:
        lines.append("  Status: FEASIBLE - battery sufficient")
    else:
        lines.append("  Status: INFEASIBLE - battery insufficient")
    lines.append("")

    all_warnings = result.warnings + geom_warnings
    if all_warnings:
        lines.append("  Warnings:")
        for w in all_warnings:
            lines.append(f"    - {w}")
    else:
        lines.append("  No warnings.")

    lines.append("=" * 50)
    return "\n".join(lines)


# ------------------------------------------------------------------
# Lost-link / fail-safe teaching demo (v1.4)
# ------------------------------------------------------------------

@dataclass
class LostLinkParams:
    """Configuration for the lost-link fail-safe demonstration.

    Attributes:
        lost_at_s: Link lost N seconds after takeoff (from waypoint 0).
        rtl_speed_ms: Cruise speed used while returning home.
        rtl_altitude_m: Altitude used for the return leg (climb if lower).
        fail_safe: Policy executed on lost link: ``"rtl"`` (default,
            return-to-launch), ``"hold"`` or ``"continue"``.
    """
    lost_at_s: float = 60.0
    rtl_speed_ms: float = 10.0
    rtl_altitude_m: float = 80.0
    fail_safe: str = "rtl"


def simulate_lost_link(
    mission: Mission,
    sim_params: SimulationParams | None = None,
    link_params: LostLinkParams | None = None,
) -> list[dict]:
    """Teaching demo: link loss at a point of the mission -> fail-safe logic.

    The demo walks through the decision process a CAAC BVLOS trainee should
    internalise: *when does the link drop, where is the aircraft, which
    fail-safe fires, how far is the return leg and does the battery cover
    it?* It intentionally narrates each step instead of hiding the logic.

    Returns:
        List of event dicts (each with ``seq``, ``type``, ``time_s``,
        optional ``lat``/``lon`` and a Chinese ``message``).

    Battery feasibility for the return leg is a teaching approximation
    based on the full-mission energy estimate: it subtracts the planned
    energy already spent before the link loss and checks the direct RTL
    leg against the leftover capacity. Waypoints are travelled at cruise
    speed with no hover (hover terms are negligible at this scale).
    """
    sim = sim_params or SimulationParams()
    link = link_params or LostLinkParams()
    wps = mission.waypoints()
    events: list[dict] = []

    if len(wps) < 2:
        return [{"seq": 1, "type": "error", "time_s": 0.0,
                 "message": "任务航点不足，无法演示链路丢失返航"}]

    eff_speed = sim.cruise_speed * sim.wind.speed_factor()
    total_time = mission.estimated_duration(hover_time=0.0)
    if eff_speed > 0:
        total_time = total_time * (sim.cruise_speed / eff_speed)
    t_lost = min(max(link.lost_at_s, 0.0), total_time)

    # ---- where is the aircraft at t_lost? ------------------------------
    seg_idx = 0
    acc = 0.0
    frac = 0.0
    for i in range(len(wps) - 1):
        leg = wps[i].distance_to(wps[i + 1])
        leg_t = leg / eff_speed if eff_speed > 0 else 0.0
        if acc + leg_t >= t_lost:
            frac = (t_lost - acc) / leg_t if leg_t > 0 else 0.0
            seg_idx = i
            break
        acc += leg_t
        seg_idx = i + 1
        frac = 0.0
    a = wps[seg_idx]
    b = wps[min(seg_idx + 1, len(wps) - 1)]
    lat = a.lat + (b.lat - a.lat) * frac
    lon = a.lon + (b.lon - a.lon) * frac
    alt = a.alt + (b.alt - a.alt) * frac

    seq = 0
    seq += 1
    events.append({"seq": seq, "type": "link_lost", "time_s": round(t_lost, 1),
                   "lat": lat, "lon": lon, "alt_m": round(alt, 1),
                   "message": (
                       f"起飞后 {t_lost:.0f} s 遥控/数传链路丢失（当前位于 WP{a.seq}-WP{b.seq} "
                       f"航段，约 {lat:.6f}, {lon:.6f}，高度 {alt:.0f} m）"
                   )})

    # remaining planned route length if the mission were to continue
    remaining = 0.0
    if seg_idx < len(wps) - 1:
        remaining += _haversine(lat, lon, wps[seg_idx + 1].lat, wps[seg_idx + 1].lon)
        for i in range(seg_idx + 1, len(wps) - 1):
            remaining += wps[i].distance_to(wps[i + 1])

    home = wps[0]
    rtl_dist = _haversine(lat, lon, home.lat, home.lon)

    seq += 1
    policy_txt = {
        "rtl": "自动返航 (RTL) —— 按民航/行业安全建议，链路丢失超时后应自动返航并降落",
        "hold": "原地悬停等待 (Hold) —— 若空域安全且电量充足可原地等待链路恢复",
        "continue": "继续执行任务 (Continue) —— 教学仅演示用途，不推荐作为生产 fail-safe",
    }.get(link.fail_safe, "自动返航 (RTL)")
    events.append({"seq": seq, "type": "policy", "time_s": round(t_lost + 5.0, 1),
                   "message": f"执行 Fail-safe 策略：{policy_txt}"})

    if link.fail_safe == "rtl":
        seq += 1
        events.append({"seq": seq, "type": "rtl_route", "time_s": round(t_lost + 5.0, 1),
                       "distance_m": round(rtl_dist, 1),
                       "message": (
                           f"直飞返航点（起降点，{home.lat:.6f}, {home.lon:.6f}）距离约 "
                           f"{rtl_dist/1000:.2f} km"
                       )})
        seq += 1
        need_climb = max(0.0, link.rtl_altitude_m - alt)
        climb_txt = f"，需先爬升至 {link.rtl_altitude_m:.0f} m（爬升 {need_climb:.0f} m）" \
            if need_climb > 0 else ""
        rtl_time = rtl_dist / max(link.rtl_speed_ms, 1e-9)
        events.append({"seq": seq, "type": "rtl_estimate", "time_s": round(t_lost + 5.0, 1),
                       "message": (
                           f"预计返航耗时约 {rtl_time/60:.1f} min（返航速度 "
                           f"{link.rtl_speed_ms:.0f} m/s{climb_txt}）"
                       )})

        # battery feasibility of the RTL leg (teaching approximation)
        full = estimate_energy(mission, sim)
        remaining_wh = sim.battery.capacity_wh * (1.0 - full.battery_used_percent / 100.0)
        rtl_wh = (sim.battery.cruise_power_w * (rtl_dist / max(link.rtl_speed_ms, 1e-9))
                  + sim.battery.hover_power_w * (link.rtl_altitude_m / max(sim.landing_speed, 1e-9))) / 3600.0
        if rtl_wh > remaining_wh:
            seq += 1
            events.append({"seq": seq, "type": "battery", "time_s": round(t_lost + 5.0, 1),
                           "message": (
                               f"[电量风险] 返航估算需 {rtl_wh:.0f} Wh，剩余可用约 "
                               f"{remaining_wh:.0f} Wh（已扣 {sim.reserve_percent:.0f}% 余量），"
                               f"不足以完成返航 —— 起飞前应复核电池余量"
                           )})
        else:
            seq += 1
            events.append({"seq": seq, "type": "battery", "time_s": round(t_lost + 5.0, 1),
                           "message": (
                               f"电量评估：返航估算需 {rtl_wh:.0f} Wh，剩余可用约 "
                               f"{remaining_wh:.0f} Wh，电量充足可完成返航"
                           )})

    seq += 1
    events.append({"seq": seq, "type": "teaching", "time_s": round(t_lost + 10.0, 1),
                   "message": (
                       f"教学提示：若链路持续丢失 {link.fail_safe.upper()} 策略将接管；"
                       f"若选择继续执行原任务，剩余航线约 {remaining/1000:.2f} km，"
                       f"而直接返航仅需 {rtl_dist/1000:.2f} km —— 超视距飞行时务必先想好"
                       f"“丢了怎么办”再起飞。"
                   )})
    return events


def format_lost_link_events(events: list[dict]) -> str:
    """Render lost-link demo events as human-readable text for the CLI."""
    lines = []
    for ev in events:
        time_txt = f"[t={ev['time_s']:>6.1f}s]" if ev.get("time_s") is not None else "[--]"
        lines.append(f"{ev['seq']:>2}. {time_txt} [{ev['type']}] {ev['message']}")
    return "\n".join(lines)
