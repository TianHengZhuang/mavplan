"""Export integrity check and plan-quality grade (v1.12)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .formats import load_mission_file, sniff_format
from .mission import Mission
from .mission_review import ReviewContext, build_mission_review
from .taskspec import Zone


def compare_missions(
    original: Mission,
    exported: Mission,
    *,
    tol_m: float = 1.0,
    tol_alt_m: float = 0.5,
) -> dict[str, Any]:
    """Compare waypoint sequences after an export/import round-trip."""
    issues: list[dict[str, Any]] = []
    o_wps = original.waypoints()
    e_wps = exported.waypoints()

    if len(o_wps) != len(e_wps):
        issues.append(
            {
                "code": "waypoint_count",
                "message": f"original {len(o_wps)} waypoints, exported {len(e_wps)}",
                "level": "error",
            }
        )

    n = min(len(o_wps), len(e_wps))
    for i in range(n):
        o, e = o_wps[i], e_wps[i]
        dlat = abs(float(o.lat) - float(e.lat))
        dlon = abs(float(o.lon) - float(e.lon))
        # rough meters
        d_m = ((dlat * 111_000) ** 2 + (dlon * 111_000 * 0.8) ** 2) ** 0.5
        dalt = abs(float(o.alt_m) - float(e.alt_m))
        if d_m > tol_m:
            issues.append(
                {
                    "code": "waypoint_position",
                    "message": f"wp#{i + 1} lat/lon drift ~{d_m:.2f} m",
                    "level": "error",
                }
            )
        if dalt > tol_alt_m:
            issues.append(
                {
                    "code": "waypoint_altitude",
                    "message": f"wp#{i + 1} alt drift {dalt:.2f} m",
                    "level": "warning",
                }
            )

    ok = not any(i["level"] == "error" for i in issues)
    return {
        "schema": "mavplan.exportcheck/1",
        "ok": ok,
        "waypoints_original": len(o_wps),
        "waypoints_exported": len(e_wps),
        "issues": issues,
    }


def export_check(
    original: Mission,
    exported_path: str | Path,
    *,
    tol_m: float = 1.0,
) -> dict[str, Any]:
    fmt = sniff_format(exported_path)
    exported = load_mission_file(exported_path)
    result = compare_missions(original, exported, tol_m=tol_m)
    result["export_format"] = fmt
    result["exported_path"] = str(exported_path)
    return result


def grade_plan_quality(
    mission: Mission,
    zones: list[Zone] | None = None,
    *,
    student: str = "",
) -> dict[str, Any]:
    """Score a *planned* mission (no flight log): preflight + structure."""
    review = build_mission_review(
        ReviewContext(mission=mission, fleet=None, zones=list(zones or []))
    )
    checks = review.get("checks") or []
    deductions: list[dict[str, Any]] = []
    score = 100.0
    for c in checks:
        level = c.get("level")
        msg = str(c.get("message") or c.get("code"))
        if level == "error":
            score -= 20.0
            deductions.append({"category": "plan_error", "message": msg, "points": 20.0})
        elif level == "warning":
            score -= 8.0
            deductions.append({"category": "plan_warning", "message": msg, "points": 8.0})
    wps = mission.waypoints()
    if len(wps) < 2:
        score -= 25.0
        deductions.append(
            {
                "category": "too_few_waypoints",
                "message": "计划航点少于 2 个",
                "points": 25.0,
            }
        )
    score = max(0.0, score)
    if score >= 90:
        band = "优秀"
    elif score >= 80:
        band = "良好"
    elif score >= 60:
        band = "合格"
    else:
        band = "不合格"
    return {
        "schema": "mavplan.grade/1",
        "mode": "plan",
        "student": student,
        "mission_name": review.get("mission_name"),
        "score": round(score, 1),
        "band": band,
        "verdict": review.get("verdict"),
        "waypoint_count": len(wps),
        "deductions": deductions,
        "review": review,
    }
