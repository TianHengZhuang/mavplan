"""Grading engine for training exams (v1.3 teaching suite).

Compares a trainee flight log against a TaskSpec brief and produces a
0-100 score with per-category deductions and a Chinese-language comment.
It builds on the existing ``compare_to_plan`` mission-vs-plan analysis by
pulling its coverage/waypoint/altitude metrics into the report payload,
while the actual grading is constraint-driven:

  - entering a no-fly zone            (per zone, -20, cap two zones)
  - missing a required waypoint       (per checkpoint, -15)
  - missing a required operating area (per area, -10)
  - cruising altitude outside window  (-10)
  - cruise speed outside window       (-10)
  - total time over the limit         (-10)
  - total distance over the limit     (-10)

The score cannot go below 0. Grade bands: >=90 优秀, >=80 良好,
>=60 合格, else 不合格.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .flightlog import FlightLog, compare_to_plan
from .mission import Mission
from .taskspec import (
    TaskSpec,
    Zone,
    haversine_m,
    point_in_circle,
    point_in_polygon,
    segment_intersects_circle,
    segment_intersects_polygon,
)

# ------------------------------------------------------------------
# Tuning constants (documented for instructors)
# ------------------------------------------------------------------
MAX_SCORE = 100.0
DEDUCT_NO_FLY_ZONE = 20.0     # per zone
DEDUCT_MISSED_POINT = 15.0    # per required waypoint
DEDUCT_MISSED_AREA = 10.0     # per required area
DEDUCT_WINDOW_ALT = 10.0
DEDUCT_WINDOW_SPEED = 10.0
DEDUCT_OVER_TIME = 10.0
DEDUCT_OVER_DISTANCE = 10.0

# Points below this altitude are considered takeoff/landing phases and are
# excluded from the altitude-window check.
_ALT_IGNORE_BELOW_M = 5.0
# A sample is considered part of the cruise core once it is this close to the
# window lower bound (covers climb/descent transitions cleanly).
_CORE_ENTER_PAD_M = 2.0
# Fraction of valid samples allowed outside a window before deducting.
_WINDOW_TOLERANCE_FRAC = 0.02
# Speed sensor noise tolerance when checking the lower speed bound.
_SPEED_MIN_TOLERANCE = 0.5
# Minimum speed sample that counts as "in flight" for the speed check.
_SPEED_AIRBORNE = 0.5
# Grace beyond the declared limit before calling it a violation.
_TIME_GRACE_S = 2.0
_DIST_GRACE_M = 10.0


@dataclass
class Deduction:
    """One grading penalty line (rendered in report + Chinese comment)."""
    category: str   # stable key: no_fly_zone / missed_checkpoint / altitude_window / speed_window / over_time / over_distance
    message: str    # human-readable Chinese description
    points: float   # how many points deducted

    def to_dict(self) -> dict:
        return {"category": self.category, "message": self.message, "points": round(self.points, 1)}


@dataclass
class GradeResult:
    """Outcome of grading one flight against one task brief."""
    student: str
    task_name: str
    score: float
    deductions: list[Deduction] = field(default_factory=list)
    comment: str = ""
    metrics: dict = field(default_factory=dict)

    @property
    def level(self) -> str:
        if self.score >= 90:
            return "优秀"
        if self.score >= 80:
            return "良好"
        if self.score >= 60:
            return "合格"
        return "不合格"

    @property
    def passed(self) -> bool:
        return self.score >= 60

    def to_dict(self) -> dict:
        return {
            "student": self.student,
            "task_name": self.task_name,
            "score": round(self.score, 1),
            "level": self.level,
            "passed": self.passed,
            "deductions": [d.to_dict() for d in self.deductions],
            "comment": self.comment,
            "metrics": self.metrics,
        }


# ------------------------------------------------------------------
# Core grading
# ------------------------------------------------------------------

def grade_flight(
    task: TaskSpec,
    flight: FlightLog,
    plan: Optional[Mission] = None,
    student: str = "",
) -> GradeResult:
    """Grade ``flight`` against ``task`` constraints.

    Args:
        task: TaskSpec brief with checkpoints, windows, limits and zones.
        flight: Trainee flight log (CSV telemetry).
        plan: Optional planned Mission used only for comparison metrics and
            the trajectory-overlay section of the report (not for scoring).
        student: Trainee display name.

    Returns:
        GradeResult with score, per-category deductions and Chinese comment.
    """
    deductions: list[Deduction] = []
    metrics: dict = {
        "num_points": len(flight.points),
        "total_distance_m": round(flight.stats().total_distance_m, 1),
        "flight_duration_s": round(_flight_duration(flight), 1),
        "max_altitude_m": round(flight.stats().max_altitude_m, 1),
        "avg_speed_mps": round(flight.stats().avg_speed_mps, 1),
        "max_speed_mps": round(flight.stats().max_speed_mps, 1),
    }

    # ---- no-fly zones -------------------------------------------------
    zone_hits: list[dict] = []
    for zone in task.no_fly_zones:
        hit = _find_zone_penetration(flight, zone)
        if hit is not None:
            idx, when = hit
            zone_hits.append({"name": zone.name, "idx": idx, "time_s": when})
            if zone.kind == "polygon":
                detail = f"进入多边形禁飞区「{zone.name}」内部({zone.shape_label()})"
            else:
                detail = (
                    f"进入禁飞区「{zone.name}」(t≈{when:.0f}s，第 {idx} 个采样点)："
                    f"与禁飞区中心最近 {zone.radius_m:.0f}m 半径内"
                )
            deductions.append(Deduction(
                category="no_fly_zone",
                message=(
                    f"{detail}。空域安全为最高优先级，"
                    f"扣除 {DEDUCT_NO_FLY_ZONE:.0f} 分"
                ),
                points=DEDUCT_NO_FLY_ZONE,
            ))
    metrics["no_fly_zone_hits"] = zone_hits

    # ---- required checkpoints -----------------------------------------
    checkpoint_metrics: list[dict] = []
    for cp in task.required:
        nearest = _nearest_flight_distance(flight, cp.lat, cp.lon)
        reached = nearest is not None and nearest <= cp.radius_m
        checkpoint_metrics.append({
            "name": cp.name, "kind": cp.kind,
            "radius_m": cp.radius_m, "nearest_m": round(nearest or 0.0, 1),
            "reached": reached,
        })
        if not reached:
            kind_label = "必过航点" if cp.kind == "point" else "作业区域"
            unit_label = "允差" if cp.kind == "point" else "区域半径"
            deduct = DEDUCT_MISSED_POINT if cp.kind == "point" else DEDUCT_MISSED_AREA
            dist_txt = f"最近飞行点距目标 {nearest:.0f}m，超过{unit_label} {cp.radius_m:.0f}m" if nearest is not None \
                else "飞行轨迹无有效采样点"
            deductions.append(Deduction(
                category="missed_checkpoint",
                message=f"未到达{kind_label}「{cp.name}」({dist_txt})，扣除 {deduct:.0f} 分",
                points=deduct,
            ))
    metrics["checkpoints"] = checkpoint_metrics

    # ---- altitude window ----------------------------------------------
    # Window checks apply to the cruise core only: samples between first and
    # last contact with the window lower bound. This keeps the vertical
    # climb-out and final descent from being counted as window violations,
    # while any mid-route sag below the window is still penalised.
    alt_ratio, alt_reached = _cruise_window_violation_ratio(flight, task.altitude_range[0], task.altitude_range[1])
    metrics["altitude_window"] = {
        "range_m": list(task.altitude_range),
        "violation_ratio": alt_ratio,
        "reached_window": alt_reached,
    }
    if alt_reached and alt_ratio > _WINDOW_TOLERANCE_FRAC:
        deductions.append(Deduction(
            category="altitude_window",
            message=(
                f"巡航高度越窗：任务书要求 {task.altitude_range[0]:.0f}~{task.altitude_range[1]:.0f}m，"
                f"巡航核心段 {alt_ratio*100:.0f}% 的采样点超窗 (容差 {_WINDOW_TOLERANCE_FRAC*100:.0f}%)，"
                f"扣除 {DEDUCT_WINDOW_ALT:.0f} 分"
            ),
            points=DEDUCT_WINDOW_ALT,
        ))
    elif not alt_reached and task.altitude_range[0] > _ALT_IGNORE_BELOW_M + 1.0:
        # Flight never climbed into the window band at all.
        max_alt = metrics.get("max_altitude_m", 0.0)
        deductions.append(Deduction(
            category="altitude_window",
            message=(
                f"巡航高度严重不足：任务书要求巡航高度 {task.altitude_range[0]:.0f}~{task.altitude_range[1]:.0f}m，"
                f"全程最大高度仅 {max_alt:.0f}m，未进入巡航高度窗口，扣除 {DEDUCT_WINDOW_ALT:.0f} 分"
            ),
            points=DEDUCT_WINDOW_ALT,
        ))

    # ---- speed window --------------------------------------------------
    spd_ratio, _ = _cruise_window_violation_ratio(
        flight, task.speed_range[0] - _SPEED_MIN_TOLERANCE, task.speed_range[1],
        height_lo=task.altitude_range[0],
        value_fn=lambda p: p.speed, use_speed=True,
    )
    metrics["speed_window"] = {
        "range_mps": list(task.speed_range),
        "violation_ratio": spd_ratio,
    }
    if spd_ratio > _WINDOW_TOLERANCE_FRAC:
        deductions.append(Deduction(
            category="speed_window",
            message=(
                f"飞行速度越窗：任务书要求 {task.speed_range[0]:.0f}~{task.speed_range[1]:.0f}m/s，"
                f"巡航核心段 {spd_ratio*100:.0f}% 的有效采样点越窗，扣除 {DEDUCT_WINDOW_SPEED:.0f} 分"
            ),
            points=DEDUCT_WINDOW_SPEED,
        ))

    # ---- time & distance limits ---------------------------------------
    duration = _flight_duration(flight)
    metrics["time_limit_s"] = task.max_time_s
    if duration > task.max_time_s + _TIME_GRACE_S:
        deductions.append(Deduction(
            category="over_time",
            message=(
                f"飞行超时：实际用时 {duration:.0f}s，超过任务时限 {task.max_time_s:.0f}s"
                f"(含 {_TIME_GRACE_S:.0f}s 容差)，扣除 {DEDUCT_OVER_TIME:.0f} 分"
            ),
            points=DEDUCT_OVER_TIME,
        ))

    total_dist = flight.stats().total_distance_m
    metrics["distance_limit_m"] = task.max_distance_m
    if total_dist > task.max_distance_m + _DIST_GRACE_M:
        deductions.append(Deduction(
            category="over_distance",
            message=(
                f"飞行超距：实际航程 {total_dist:.0f}m，超过任务限定 {task.max_distance_m:.0f}m"
                f"(含 {_DIST_GRACE_M:.0f}m 容差)，扣除 {DEDUCT_OVER_DISTANCE:.0f} 分"
            ),
            points=DEDUCT_OVER_DISTANCE,
        ))

    # ---- compare_to_plan metrics (mission-vs-plan view) ---------------
    if plan is not None and flight.points and plan.waypoints():
        try:
            metrics["compare_to_plan"] = compare_to_plan(flight, plan)
        except Exception:
            metrics["compare_to_plan"] = {"error": "plan comparison failed"}

    # ---- score & comment ----------------------------------------------
    total_deduct = sum(d.points for d in deductions)
    score = max(0.0, MAX_SCORE - total_deduct)
    comment = _build_comment(score, deductions)

    return GradeResult(
        student=student or "未命名学员",
        task_name=task.name,
        score=round(score, 1),
        deductions=deductions,
        comment=comment,
        metrics=metrics,
    )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _flight_duration(flight: FlightLog) -> float:
    if not flight.points:
        return 0.0
    return max(0.0, flight.points[-1].time_s - flight.points[0].time_s)


def _nearest_flight_distance(flight: FlightLog, lat: float, lon: float) -> Optional[float]:
    """Closest distance (m) between any flight point and (lat, lon)."""
    if not flight.points:
        return None
    return min(haversine_m(lat, lon, p.lat, p.lon) for p in flight.points)


def _find_zone_penetration(flight: FlightLog, zone: Zone):
    """Return (point_index, time_s) of first entry into ``zone``, or None.

    Supports circle and polygon zones. Pure tangency does NOT count as an
    entry (a flight that only grazes the boundary is not penalised), which
    mirrors ``point_in_circle`` / ``segment_intersects_circle`` semantics.
    """
    pts = flight.points
    if not pts:
        return None

    if zone.kind == "polygon":
        ring = zone.polygon_ring()
        if len(ring) < 3:
            return None
        for i, p in enumerate(pts):
            if point_in_polygon(p.lat, p.lon, ring):
                return i, p.time_s
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if segment_intersects_polygon(a.lat, a.lon, b.lat, b.lon, ring):
                return i, a.time_s
        return None

    c_lat, c_lon, radius_m = zone.lat, zone.lon, zone.radius_m
    for i, p in enumerate(pts):
        if point_in_circle(p.lat, p.lon, c_lat, c_lon, radius_m):
            return i, p.time_s
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        if segment_intersects_circle(a.lat, a.lon, b.lat, b.lon, c_lat, c_lon, radius_m):
            return i, a.time_s
    return None


def _cruise_span(flight: FlightLog, window_lo: float) -> Optional[tuple[int, int]]:
    """Index span [start, end] of the cruise core.

    The cruise core starts at the first sample whose altitude approaches the
    window lower bound (within ``_CORE_ENTER_PAD_M``) and ends at the last
    such sample. Returns None when the flight never reached the window band
    (e.g. always too low).
    """
    pts = flight.points
    if not pts:
        return None
    bound = window_lo - _CORE_ENTER_PAD_M
    hits = [i for i, p in enumerate(pts) if p.alt >= bound]
    if not hits:
        return None
    return hits[0], hits[-1]


def _cruise_window_violation_ratio(
    flight: FlightLog,
    lo: float,
    hi: float,
    height_lo: Optional[float] = None,
    value_fn=lambda p: p.alt,
    use_speed: bool = False,
) -> tuple[float, bool]:
    """Fraction of cruise-core samples outside [lo, hi] and whether the
    flight ever reached the window band.

    The cruise core is always derived from the altitude window lower bound
    (``height_lo``, defaulting to ``lo``): samples between first and last
    contact with that bound. For altitude checks every core sample counts
    (any mid-route sag is penalised); for speed checks only airborne samples
    (speed > 0.5 m/s) are measured.
    """
    pts = flight.points
    if not pts:
        return 0.0, False
    span = _cruise_span(flight, height_lo if height_lo is not None else lo)
    if span is None:
        # Never climbed near the band: report violations over all airborne
        # altitude samples as a worst-case ratio.
        airborne = [p for p in pts if p.alt >= _ALT_IGNORE_BELOW_M]
        if not airborne:
            return 0.0, False
        bad = sum(1 for p in airborne if not (lo <= value_fn(p) <= hi))
        return bad / len(airborne), False

    start, end = span
    core = pts[start:end + 1]
    if use_speed:
        core = [p for p in core if p.speed > _SPEED_AIRBORNE]
    if not core:
        return 0.0, True
    bad = sum(1 for p in core if not (lo <= value_fn(p) <= hi))
    return bad / len(core), True


def _build_comment(score: float, deductions: list[Deduction]) -> str:
    """Compose a Chinese grade comment from the score and deduction list."""
    if score >= 90:
        head = "成绩优秀"
    elif score >= 80:
        head = "成绩良好"
    elif score >= 60:
        head = "成绩合格"
    else:
        head = "成绩不合格"

    if not deductions:
        return (
            f"{head}（{score:.1f} 分）。飞行轨迹与任务书要求高度吻合：全部必达航点/区域均已到达，"
            "未进入禁飞区，高度、速度、用时与航程均满足窗口要求。请继续保持规范的航线规划与"
            "执行习惯，注意检查禁飞区与极限参数后再起飞。"
        )

    parts = [f"{head}（{score:.1f} 分），本次飞行共发现 {len(deductions)} 项问题："]
    for i, d in enumerate(deductions, 1):
        parts.append(f"{i}. {d.message}")
    parts.append("")

    tips = _improvement_tips(deductions)
    if tips:
        parts.append("改进建议：" + "；".join(tips) + "。")
    else:
        parts.append("请对照扣分明细复核任务书要求后重新规划航线。")
    return "\n".join(parts)


def _improvement_tips(deductions: list[Deduction]) -> list[str]:
    cats = {d.category for d in deductions}
    tips: list[str] = []
    if "no_fly_zone" in cats:
        tips.append("飞行前务必在任务书/航图中确认禁飞区位置，规划航线须与禁飞区保持安全间隔")
    if "missed_checkpoint" in cats:
        tips.append("重新核对任务书必达航点与作业区域，确保航线完整覆盖所有考核点")
    if "altitude_window" in cats:
        tips.append("巡航段应稳定保持任务书规定的高度窗口，避免爬升/下降幅度过大")
    if "speed_window" in cats:
        tips.append("控制巡航速度在任务书窗口内，保持匀速飞行以减少越窗")
    if "over_time" in cats:
        tips.append("优化航线走向与巡航速度，为考核预留时间余量")
    if "over_distance" in cats:
        tips.append("精简航线长度，避免绕飞导致超距")
    return tips
