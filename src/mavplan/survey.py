"""v1.5 survey / photogrammetry teaching module.

Camera model + imaging math (FOV, footprint, GSD), overlap-based route
spacing, and coverage validation for the training scenario of the mavplan
roadmap:

  1. Camera model: sensor size / focal length / pixels -> FOV, GSD,
     single-image ground footprint.
  2. Overlap computation: camera FOV + survey altitude -> lane spacing
     (side overlap) and shutter spacing (forward overlap). The CLI
     ``generate lawnmower --camera`` helper consumes the same math.
  3. Coverage validation: given an EW lawn-mower mission (each lane is a
     pair of consecutive waypoints sharing the same latitude), compute the
     theoretical ground coverage ratio of the swath bands against the
     mission bounding rectangle.

All formulas follow the classical photogrammetry textbook relations
(GSD = pixel pitch x H / f; footprint = sensor dimension x H / f) and are
kept dependency-free so the repository keeps its "zero new runtime
dependency" rule. Unit tests compare the numbers against hand calculations
within +-1%.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Iterable, Optional

from .mission import Mission

_M_PER_DEG_LAT = 111_320.0

# ----------------------------------------------------------------------
# Camera presets (teaching defaults -- real values should come from the
# camera calibration report / manufacturer datasheet).
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Camera:
    """Simple photogrammetry camera model (nadir-looking, no distortion).

    Attributes:
        name: Identifier used by CLI presets (e.g. ``p4rtk``).
        sensor_width_mm: Width of the imaging sensor (mm) -- the dimension
            that is placed *across* the flight track in the examples below.
        sensor_height_mm: Height of the imaging sensor (mm) -- along track.
        focal_length_mm: Equivalent focal length (mm).
        sensor_width_px: Pixel count along the sensor width.
        sensor_height_px: Pixel count along the sensor height.
        note: Optional Chinese note shown in teaching pages / CLI output.
    """

    name: str
    sensor_width_mm: float
    sensor_height_mm: float
    focal_length_mm: float
    sensor_width_px: int
    sensor_height_px: int
    note: str = ""

    def pixel_pitch_width_mm(self) -> float:
        return self.sensor_width_mm / self.sensor_width_px

    def pixel_pitch_height_mm(self) -> float:
        return self.sensor_height_mm / self.sensor_height_px

    def fov_h_deg(self) -> float:
        """Horizontal field of view (deg), across the sensor width."""
        return math.degrees(2.0 * math.atan((self.sensor_width_mm / 2.0) / self.focal_length_mm))

    def fov_v_deg(self) -> float:
        """Vertical field of view (deg), along the sensor height."""
        return math.degrees(2.0 * math.atan((self.sensor_height_mm / 2.0) / self.focal_length_mm))

    def footprint_across_m(self, altitude_m: float) -> float:
        """Ground footprint across the track (m) at a given altitude."""
        return self.sensor_width_mm / self.focal_length_mm * altitude_m

    def footprint_along_m(self, altitude_m: float) -> float:
        """Ground footprint along the track (m) at a given altitude."""
        return self.sensor_height_mm / self.focal_length_mm * altitude_m

    def gsd_m(self, altitude_m: float) -> dict:
        """Ground sample distance (m) at a given altitude.

        ``gsd_across_m`` / ``gsd_along_m`` are the per-axis values
        (pixel pitch x H / f).  ``gsd_m`` is the conservative worst-case
        value used for pass/fail checks.
        """
        gsd_across = self.pixel_pitch_width_mm() * altitude_m / self.focal_length_mm
        gsd_along = self.pixel_pitch_height_mm() * altitude_m / self.focal_length_mm
        return {
            "altitude_m": altitude_m,
            "gsd_across_m": gsd_across,
            "gsd_along_m": gsd_along,
            "gsd_m": max(gsd_across, gsd_along),
        }


CAMERA_PRESETS: dict[str, Camera] = {
    "p4rtk": Camera(
        name="p4rtk",
        sensor_width_mm=13.2,
        sensor_height_mm=8.8,
        focal_length_mm=8.8,
        sensor_width_px=5472,
        sensor_height_px=3648,
        note="大疆 Phantom 4 RTK 广角相机（1 英寸 CMOS，教示默认值）",
    ),
    "mavic3e": Camera(
        name="mavic3e",
        sensor_width_mm=17.3,
        sensor_height_mm=13.0,
        focal_length_mm=12.29,
        sensor_width_px=5280,
        sensor_height_px=3956,
        note="大疆 Mavic 3 Enterprise 广角相机（4/3 CMOS，教示默认值）",
    ),
    "generic35": Camera(
        name="generic35",
        sensor_width_mm=36.0,
        sensor_height_mm=24.0,
        focal_length_mm=35.0,
        sensor_width_px=8688,
        sensor_height_px=5792,
        note="教学用通用全画幅 35mm 示例相机（禅思 P1 规格量级）",
    ),
}

_KNOWN_KEYS = ", ".join(sorted(CAMERA_PRESETS))


def camera_for(name: str) -> Camera:
    """Look up a camera preset by name (case-insensitive)."""
    key = name.strip().lower()
    if key in CAMERA_PRESETS:
        return CAMERA_PRESETS[key]
    raise ValueError(f"Unknown camera preset {name!r}. Known presets: {_KNOWN_KEYS}")


# ----------------------------------------------------------------------
# Route / trigger geometry
# ----------------------------------------------------------------------

def _check_overlap(overlap: float, label: str) -> None:
    if not 0.0 <= overlap < 1.0:
        raise ValueError(f"{label} overlap must be in [0, 1), got {overlap}")


def lane_spacing_m(camera: Camera, altitude_m: float, side_overlap: float) -> float:
    """Lane spacing from the side (lateral) overlap requirement.

    ``lane_spacing = footprint_across * (1 - side_overlap)`` so two
    neighbouring images still share ``side_overlap`` of their width.
    """
    _check_overlap(side_overlap, "side")
    return camera.footprint_across_m(altitude_m) * (1.0 - side_overlap)


def forward_spacing_m(camera: Camera, altitude_m: float, forward_overlap: float) -> float:
    """Distance between successive shutter releases along the track.

    ``forward_spacing = footprint_along * (1 - forward_overlap)``.
    """
    _check_overlap(forward_overlap, "forward")
    return camera.footprint_along_m(altitude_m) * (1.0 - forward_overlap)


def altitude_for_gsd_m(camera: Camera, gsd_target_m: float) -> float:
    """Recommended survey altitude for a target GSD (m).

    ``H = GSD * focal_length / pixel_pitch`` (worst-axis pitch).
    """
    if gsd_target_m <= 0:
        raise ValueError("gsd_target_m must be positive")
    pitch = max(camera.pixel_pitch_width_mm(), camera.pixel_pitch_height_mm())
    return gsd_target_m * camera.focal_length_mm / pitch


def survey_plan(
    camera: Camera,
    altitude_m: float,
    side_overlap: float = 0.60,
    forward_overlap: float = 0.70,
) -> dict:
    """One-stop camera/survey calculation for a given altitude.

    Returns a dict with all teaching numbers (FOV, GSD, footprints,
    recommended lane / shutter spacing).
    """
    gsd = camera.gsd_m(altitude_m)
    lane = lane_spacing_m(camera, altitude_m, side_overlap)
    fwd = forward_spacing_m(camera, altitude_m, forward_overlap)
    return {
        "camera_name": camera.name,
        "altitude_m": altitude_m,
        "side_overlap": side_overlap,
        "forward_overlap": forward_overlap,
        "fov_h_deg": camera.fov_h_deg(),
        "fov_v_deg": camera.fov_v_deg(),
        "footprint_across_m": camera.footprint_across_m(altitude_m),
        "footprint_along_m": camera.footprint_along_m(altitude_m),
        "gsd_across_m": gsd["gsd_across_m"],
        "gsd_along_m": gsd["gsd_along_m"],
        "gsd_m": gsd["gsd_m"],
        "recommended_lane_spacing_m": lane,
        "recommended_forward_spacing_m": fwd,
    }


# ----------------------------------------------------------------------
# Mission analysis helpers (EW lawn-mower routes)
# ----------------------------------------------------------------------

def extract_ew_rows(mission: Mission, lat_tol_m: float = 1e-3) -> list[dict]:
    """Extract EW (east-west) survey lanes from a lawn-mower style mission.

    The v1.1 ``generate lawnmower`` emits lanes as consecutive waypoint
    pairs that share the same latitude.  This helper groups those pairs
    into ``[{'lat':..., 'lon_a':..., 'lon_b':...}, ...]`` rows.

    Returns [] when the mission does not look like an EW lawn-mower route.
    """
    wps = mission.waypoints()
    rows: list[dict] = []
    i = 0
    deg_per_m = 1.0 / _M_PER_DEG_LAT
    while i < len(wps):
        a = wps[i]
        if i + 1 >= len(wps):
            break
        b = wps[i + 1]
        lat_gap_m = abs(a.lat - b.lat) / deg_per_m
        lon_gap_m = abs(a.lon - b.lon) / max(deg_per_m * math.cos(math.radians(a.lat)), 1e-12)
        if lat_gap_m <= lat_tol_m and lon_gap_m > 0.5:
            rows.append(
                {"lat": a.lat,
                 "lon_a": min(a.lon, b.lon),
                 "lon_b": max(a.lon, b.lon),
                 "alt_m": (a.alt + b.alt) / 2.0}
            )
            i += 2
            continue
        i += 1
    return rows


def row_latitudes_m(rows: Iterable[dict], lat0: float) -> list[float]:
    """Latitudes of the extracted rows converted to metres offset from lat0."""
    deg_per_m = 1.0 / _M_PER_DEG_LAT
    out = []
    for r in rows:
        out.append((r["lat"] - lat0) / deg_per_m)
    out.sort()
    return out


def actual_lane_spacing_m(rows: Iterable[dict], lat0: float) -> Optional[float]:
    """Median spacing between consecutive lanes (m), or None if < 2 lanes."""
    lats = row_latitudes_m(rows, lat0)
    if len(lats) < 2:
        return None
    gaps = [b - a for a, b in zip(lats, lats[1:]) if b - a > 1e-9]
    if not gaps:
        return None
    gaps.sort()
    return gaps[len(gaps) // 2]


# ----------------------------------------------------------------------
# Coverage validation
# ----------------------------------------------------------------------

def _bbox_m(mission: Mission, lat0: float, lon0: float) -> dict:
    deg_per_m = 1.0 / _M_PER_DEG_LAT
    wps = mission.waypoints()
    if not wps:
        raise ValueError("mission has no waypoints")
    lat_m = [(wp.lat - lat0) / deg_per_m for wp in wps]
    lon_cos = max(math.cos(math.radians(lat0)), 1e-12)
    lon_m = [(wp.lon - lon0) / (deg_per_m * lon_cos) for wp in wps]
    return {
        "ymin_m": min(lat_m),
        "ymax_m": max(lat_m),
        "xmin_m": min(lon_m),
        "xmax_m": max(lon_m),
    }


def coverage_ratio(
    mission: Mission,
    camera: Camera,
    side_overlap: float = 0.60,
    forward_overlap: float = 0.70,
    lat0: Optional[float] = None,
    lon0: Optional[float] = None,
    step_m: Optional[float] = None,
) -> dict:
    """Theoretical ground coverage of an EW lawn-mower mission.

    Each lane is covered by a continuous swath band of width equal to the
    camera's across-track footprint at the lane altitude.  The mission
    bounding rectangle (the survey area implied by ``generate lawnmower``)
    is sampled on a regular grid; a sample is "covered" when it falls inside
    at least one lane band.  Returns the ratio and cell statistics.

    This intentionally ignores turn gaps outside the rectangle and assumes
    a nadir camera -- the number is a teaching "theoretical coverage"
    figure, not a flight-simulator product.
    """
    rows = extract_ew_rows(mission)
    if not rows:
        return {
            "coverage_ratio": 0.0,
            "covered_cells": 0,
            "total_cells": 0,
            "error": "mission is not an EW lawn-mower route (no constant-lat lane pairs)",
        }

    wps = mission.waypoints()
    lat0 = lat0 if lat0 is not None else wps[0].lat
    lon0 = lon0 if lon0 is not None else wps[0].lon
    bbox = _bbox_m(mission, lat0, lon0)
    area_w_m = bbox["xmax_m"] - bbox["xmin_m"]
    area_h_m = bbox["ymax_m"] - bbox["ymin_m"]
    if area_w_m < 1e-6 or area_h_m < 1e-6:
        return {"coverage_ratio": 0.0, "covered_cells": 0, "total_cells": 0,
                "error": "survey area is degenerate"}

    alt = rows[0]["alt_m"]
    fp_across = camera.footprint_across_m(alt)
    fp_along = camera.footprint_along_m(alt)
    if fp_across <= 0 or fp_along <= 0:
        raise ValueError("camera footprint must be positive")

    step = step_m or max(min(fp_across, fp_along) / 40.0, 1.0)
    # Keep the sample grid sane for huge areas: never more than ~800 lines
    step = max(step, max(area_w_m, area_h_m) / 800.0)

    half_across = fp_across / 2.0
    # each row: x interval [lon_a, lon_b] with a small along-track allowance
    half_along = fp_along / 2.0

    # grid cell centres
    nx = max(1, int(math.ceil(area_w_m / step)))
    ny = max(1, int(math.ceil(area_h_m / step)))
    covered = 0
    total = 0
    # Pre-scale to local metre coords to make grid sampling cheaper.
    deg_per_m = 1.0 / _M_PER_DEG_LAT
    lon_cos = max(math.cos(math.radians(lat0)), 1e-12)
    bands = []
    for r in rows:
        y = (r["lat"] - lat0) / deg_per_m
        xa = (r["lon_a"] - lon0) / (deg_per_m * lon_cos)
        xb = (r["lon_b"] - lon0) / (deg_per_m * lon_cos)
        bands.append((y, min(xa, xb), max(xa, xb)))
    # sort bands by y for early exit
    bands.sort(key=lambda b: b[0])

    for jy in range(ny + 1):
        y = bbox["ymin_m"] + jy * area_h_m / ny
        hit_row = False
        for (by, xa, xb) in bands:
            if abs(y - by) <= half_across + 1e-9:
                hit_row = True
                break
        for jx in range(nx + 1):
            x = bbox["xmin_m"] + jx * area_w_m / nx
            total += 1
            covered_flag = False
            for (by, xa, xb) in bands:
                if y < by - half_across - 1e-9:
                    break
                if abs(y - by) <= half_across + 1e-9 and xa - half_along - 1e-9 <= x <= xb + half_along + 1e-9:
                    covered_flag = True
                    break
            if covered_flag:
                covered += 1

    return {
        "coverage_ratio": covered / total,
        "covered_cells": covered,
        "total_cells": total,
        "step_m": step,
        "bands": len(bands),
    }


# ----------------------------------------------------------------------
# Survey check (auto grading)
# ----------------------------------------------------------------------

def survey_check(
    mission: Mission,
    camera: Camera,
    side_overlap: float = 0.60,
    forward_overlap: float = 0.70,
    gsd_max_m: Optional[float] = None,
    alt_fallback_m: Optional[float] = None,
) -> dict:
    """Grade a survey mission against camera/overlap/GSD requirements.

    Returns a dict with computed plan numbers and a structured item list
    (code / level / waypoint / message) in the same style as the v1.4
    preflight check, plus ``passed`` (True when no error-level item).
    """
    rows = extract_ew_rows(mission)
    wps = mission.waypoints()
    if not wps:
        return {
            "passed": False,
            "items": [
                {"code": "empty-mission", "level": "error", "waypoint": "",
                 "message": "mission has no waypoints"}
            ],
        }

    alts = [wp.alt for wp in wps]
    alt = alt_fallback_m or (sum(alts) / len(alts))
    plan = survey_plan(camera, alt, side_overlap, forward_overlap)
    items: list[dict] = []

    # --- GSD ---------------------------------------------------------
    gsd_worst = max(camera.gsd_m(a)["gsd_m"] for a in alts)
    if gsd_max_m is not None:
        if gsd_worst <= gsd_max_m:
            items.append({
                "code": "gsd-ok",
                "level": "ok",
                "waypoint": "",
                "message": f"最差 GSD {gsd_worst * 100:.1f} cm ≤ 要求 {gsd_max_m * 100:.1f} cm",
            })
        else:
            worst_alt = max(alts)
            items.append({
                "code": "gsd-exceeded",
                "level": "error",
                "waypoint": f"alt={worst_alt:.1f} m",
                "message": (
                    f"GSD 超限：{gsd_worst * 100:.1f} cm > 要求 {gsd_max_m * 100:.1f} cm；"
                    f"建议航高 ≤ {altitude_for_gsd_m(camera, gsd_max_m):.1f} m"
                ),
            })

    # --- lane spacing / side overlap ---------------------------------
    if len(rows) < 2:
        items.append({
            "code": "overlap-not-checkable",
            "level": "warning",
            "waypoint": "",
            "message": "少于 2 条同纬航线，无法检查旁向重叠",
        })
    else:
        lat0 = wps[0].lat
        actual = actual_lane_spacing_m(rows, lat0) or 0.0
        required = plan["recommended_lane_spacing_m"]
        if actual <= required * 1.005:
            items.append({
                "code": "side-overlap-ok",
                "level": "ok",
                "waypoint": "",
                "message": (
                    f"实测行距 {actual:.1f} m ≤ 理论行距 {required:.1f} m "
                    f"（旁向重叠 ≥ {side_overlap * 100:.0f}%）"
                ),
            })
        else:
            actual_overlap = max(0.0, 1.0 - actual / max(plan["footprint_across_m"], 1e-9))
            items.append({
                "code": "side-overlap-low",
                "level": "error",
                "waypoint": "",
                "message": (
                    f"旁向重叠不足：实测行距 {actual:.1f} m > 理论 {required:.1f} m，"
                    f"实测重叠约 {actual_overlap * 100:.0f}% < {side_overlap * 100:.0f}%"
                ),
            })

    # --- forward spacing (informational guidance) ---------------------
    fwd = plan["recommended_forward_spacing_m"]
    items.append({
        "code": "forward-spacing",
        "level": "info",
        "waypoint": "",
        "message": (
            f"建议拍照间距 {fwd:.1f} m（航向重叠 {forward_overlap * 100:.0f}%）；"
            "请按此设置 DO_SET_CAM_TRIGG_DIST / 相机定时器"
        ),
    })

    # --- coverage ------------------------------------------------------
    cov = coverage_ratio(mission, camera, side_overlap, forward_overlap, lat0=wps[0].lat, lon0=wps[0].lon)
    if cov.get("error"):
        items.append({
            "code": "coverage-not-checkable",
            "level": "warning",
            "waypoint": "",
            "message": cov["error"],
        })
        ratio = 0.0
    else:
        ratio = cov["coverage_ratio"]
        if ratio >= 0.90:
            items.append({
                "code": "coverage-ok",
                "level": "ok",
                "waypoint": "",
                "message": f"理论覆盖率 {ratio * 100:.1f}%",
            })
        else:
            items.append({
                "code": "coverage-low",
                "level": "error",
                "waypoint": "",
                "message": f"理论覆盖率 {ratio * 100:.1f}% < 90%，请检查航高/行距",
            })

    passed = not any(it["level"] == "error" for it in items)
    result = {
        "passed": passed,
        "camera_name": camera.name,
        "camera_note": camera.note,
        "altitude_m": alt,
        "plan": plan,
        "rows": len(rows),
        "gsd_worst_cm": gsd_worst * 100.0,
        "coverage_ratio": ratio,
        "items": items,
        "summary_text": ("GSD 与重叠率达标，测绘航线可用。"
                         if passed
                         else "存在不达标项，请按检查明细调整航高或行距后重测。"),
    }
    return result


# ----------------------------------------------------------------------
# Teaching / lesson content (Chinese, used by CLI and the HTML report)
# ----------------------------------------------------------------------

def lesson_sections(plan: dict) -> list[dict]:
    """Chinese lesson cards explaining the photogrammetry formulas."""
    cam = plan["camera_name"]
    return [
        {
            "title": "1. 视场角（FOV）",
            "text": (
                f"视场角由传感器边长与焦距决定：FOV = 2·arctan(边长 / (2·焦距))。"
                f"本相机横向 {plan['fov_h_deg']:.1f}°、纵向 {plan['fov_v_deg']:.1f}°。"
                "焦距越短、传感器越大，视场越宽。"
            ),
        },
        {
            "title": "2. 地面分辨率（GSD）",
            "text": (
                f"GSD（单像素地面尺寸）= 像元物理尺寸 × 航高 ÷ 焦距。"
                f"当前航高 {plan['altitude_m']:.0f} m 下：横向 {plan['gsd_across_m'] * 100:.2f} cm，"
                f"纵向 {plan['gsd_along_m'] * 100:.2f} cm（按较差值 {plan['gsd_m'] * 100:.2f} cm 判定）。"
                "航高越高 GSD 越大（分辨率越低）；同相机下两者线性变化。"
            ),
        },
        {
            "title": "3. 单张覆盖",
            "text": (
                f"单张照片地面覆盖 = 传感器边长 × 航高 ÷ 焦距。"
                f"横向（垂直航迹）{plan['footprint_across_m']:.0f} m，"
                f"纵向（沿航迹）{plan['footprint_along_m']:.0f} m。"
                "覆盖越宽，测区所需航线越少。"
            ),
        },
        {
            "title": "4. 重叠率与行距/拍照间距",
            "text": (
                f"旁向重叠用相邻航线照片重叠度衡量：行距 = 横向覆盖 × (1 − 旁向重叠率)，"
                f"当前建议行距 {plan['recommended_lane_spacing_m']:.1f} m。"
                f"航向重叠用同一航线上相邻照片重叠度衡量：拍照间距 = 纵向覆盖 × (1 − 航向重叠率)，"
                f"当前建议间距 {plan['recommended_forward_spacing_m']:.1f} m。"
                "经验值：一般正射航测旁向重叠 ≥ 60%、航向重叠 ≥ 70%。"
            ),
        },
        {
            "title": "5. 目标 GSD 反推航高",
            "text": (
                "航高 = 目标 GSD × 焦距 ÷ 像元尺寸。若任务书要求 GSD ≤ 5 cm，"
                "先按相机参数反推允许的最大航高，再设计航线，避免无效重飞。"
            ),
        },
    ]


def format_survey_check_text(result: dict) -> str:
    """Human-readable CLI rendering of the survey check result."""
    plan = result.get("plan") or {}
    lines = []
    lines.append(f"相机：{result.get('camera_name', '?')}（{result.get('camera_note', '')}）")
    lines.append(f"航高（任务均值）：{result.get('altitude_m', 0):.1f} m")
    if plan:
        lines.append(f"  FOV：{plan['fov_h_deg']:.1f}° × {plan['fov_v_deg']:.1f}°")
        lines.append(
            f"  覆盖：横向 {plan['footprint_across_m']:.1f} m × 纵向 {plan['footprint_along_m']:.1f} m"
        )
        lines.append(f"  GSD：{plan['gsd_m'] * 100:.2f} cm（最差航线值 {result.get('gsd_worst_cm', 0):.1f} cm）")
        lines.append(
            f"  理论行距：{plan['recommended_lane_spacing_m']:.1f} m"
            f"（旁向重叠 {plan['side_overlap'] * 100:.0f}%）"
        )
        lines.append(
            f"  建议拍照间距：{plan['recommended_forward_spacing_m']:.1f} m"
            f"（航向重叠 {plan['forward_overlap'] * 100:.0f}%）"
        )
    lines.append("")
    for it in result["items"]:
        level = {"ok": "PASS", "info": "INFO", "warning": "WARN", "error": "FAIL"}.get(it["level"], "INFO")
        suffix = f" [{it['waypoint']}]" if it.get("waypoint") else ""
        lines.append(f"  [{level}] {it['code']}{suffix}: {it['message']}")
    lines.append("")
    lines.append("判定：" + ("通过（可用）" if result["passed"] else "未通过（需调整）"))
    lines.append(result["summary_text"])
    return "\n".join(lines)
