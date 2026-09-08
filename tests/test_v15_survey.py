"""v1.5 survey & photogrammetry teaching tests.

Acceptance focus of the ROADMAP v1.5 milestone:
  - camera model (sensor/focal/pixels -> FOV, GSD, single-shot footprint)
    matches textbook photogrammetry formulas within +-1%;
  - overlap math: lane spacing / shutter spacing derived from FOV + survey
    altitude, hand-checked for a known rectangular area;
  - ``generate lawnmower --camera`` auto-computes lane spacing from the
    camera preset;
  - theoretical coverage validation for an EW lawn-mower mission;
  - survey auto-grading (GSD + side-overlap checks) is exposed through the
    CLI and the HTML lesson report.

The repository keeps its "zero new runtime dependency" rule: the module
uses only math + stdlib.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from click.testing import CliRunner

from mavplan.mission import Mission
from mavplan.survey import (
    CAMERA_PRESETS,
    Camera,
    altitude_for_gsd_m,
    camera_for,
    coverage_ratio,
    extract_ew_rows,
    forward_spacing_m,
    lane_spacing_m,
    lesson_sections,
    survey_check,
    survey_plan,
)

_M_PER_DEG = 111_320.0


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _cam() -> Camera:
    # Phantom 4 RTK style: 1" CMOS 13.2 x 8.8 mm, f = 8.8 mm, 5472 x 3648 px
    return Camera(
        name="p4rtk",
        sensor_width_mm=13.2,
        sensor_height_mm=8.8,
        focal_length_mm=8.8,
        sensor_width_px=5472,
        sensor_height_px=3648,
    )


def _area_mission(lat0: float, lon0: float, alt: float = 40.0,
                  rows: int = 3, gap_m: float = 24.0, width_m: float = 100.0) -> Mission:
    m = Mission(name="v1.5 survey area")
    for i in range(rows):
        lat = lat0 + i * gap_m / _M_PER_DEG
        lon_a = lon0
        lon_b = lon0 + width_m / (_M_PER_DEG * max(math.cos(math.radians(lat)), 1e-12))
        m.add_waypoint(lat=lat, lon=lon_a, alt=alt)
        m.add_waypoint(lat=lat, lon=lon_b, alt=alt)
    return m


# ----------------------------------------------------------------------
# camera model
# ----------------------------------------------------------------------

class TestCameraModel:
    def test_fov_hand_formula(self):
        cam = _cam()
        # FOV_h = 2*atan((13.2/2)/8.8) = 2*atan(0.75) = 73.74 deg
        expected = 2.0 * math.degrees(math.atan(13.2 / 2.0 / 8.8))
        assert cam.fov_h_deg() == pytest.approx(expected, rel=1e-6)
        # 2*atan(4.4/8.8) = 2*atan(0.5) = 53.13 deg
        assert cam.fov_v_deg() == pytest.approx(2.0 * math.degrees(math.atan(0.5)), rel=1e-6)

    def test_gsd_hand_formula(self):
        cam = _cam()
        alt = 40.0
        # gsd (m) = pixel_pitch (mm) * H (m) / focal (mm); p4rtk across pitch
        # = 13.2/5472 mm, so across GSD at 40 m = 1.096 cm = 0.01096 m.
        expected_across = (13.2 / 5472.0) * alt / 8.8  # metres
        gsd = cam.gsd_m(alt)
        assert gsd["gsd_across_m"] == pytest.approx(expected_across, rel=1e-9)
        expected_along = (8.8 / 3648.0) * alt / 8.8
        assert gsd["gsd_along_m"] == pytest.approx(expected_along, rel=1e-9)
        # worst axis across (bigger pixel pitch)
        assert gsd["gsd_m"] == max(expected_across, expected_along)

    def test_footprint_hand_formula(self):
        cam = _cam()
        alt = 50.0
        assert cam.footprint_across_m(alt) == pytest.approx(13.2 / 8.8 * alt, rel=1e-6)
        assert cam.footprint_along_m(alt) == pytest.approx(8.8 / 8.8 * alt, rel=1e-6)

    def test_overlap_spacing_hand_formula(self):
        cam = _cam()
        alt = 40.0
        lane = lane_spacing_m(cam, alt, 0.6)
        assert lane == pytest.approx(13.2 / 8.8 * alt * (1 - 0.6), rel=1e-9)
        fwd = forward_spacing_m(cam, alt, 0.7)
        assert fwd == pytest.approx(8.8 / 8.8 * alt * (1 - 0.7), rel=1e-9)

    def test_overlap_invalid_range(self):
        cam = _cam()
        with pytest.raises(ValueError):
            lane_spacing_m(cam, 50, 1.0)
        with pytest.raises(ValueError):
            forward_spacing_m(cam, 50, -0.1)

    def test_altitude_for_gsd(self):
        cam = _cam()
        # pitch_worst = 13.2/5472; H = gsd*focal/pitch
        gsd_t = 0.02
        expected = gsd_t * 8.8 / (13.2 / 5472.0)
        assert altitude_for_gsd_m(cam, gsd_t) == pytest.approx(expected, rel=1e-9)

    def test_presets_available(self):
        assert "p4rtk" in CAMERA_PRESETS
        cam = camera_for("P4RTK")
        assert cam.name == "p4rtk"
        with pytest.raises(ValueError):
            camera_for("does-not-exist")

    def test_survey_plan_consistent(self):
        cam = _cam()
        plan = survey_plan(cam, 60.0, side_overlap=0.6, forward_overlap=0.7)
        assert plan["gsd_m"] == cam.gsd_m(60.0)["gsd_m"]
        assert plan["recommended_lane_spacing_m"] == pytest.approx(
            lane_spacing_m(cam, 60.0, 0.6)
        )

    def test_lesson_sections_cover_roadmap_terms(self):
        cam = _cam()
        plan = survey_plan(cam, 40.0)
        text = "\n".join(s["text"] for s in lesson_sections(plan))
        for term in ["FOV", "GSD", "覆盖", "行距", "重叠", "航高"]:
            assert term in text


# ----------------------------------------------------------------------
# mission rows & coverage
# ----------------------------------------------------------------------

class TestCoverage:
    def test_extract_ew_rows(self):
        m = _area_mission(lat0=0.0, lon0=0.0, rows=3, gap_m=24.0)
        rows = extract_ew_rows(m)
        assert len(rows) == 3
        lats = sorted(r["lat"] for r in rows)
        # metre gaps restored within 1e-3 m
        for a, b in zip(lats, lats[1:]):
            assert (b - a) * _M_PER_DEG == pytest.approx(24.0, rel=1e-3)

    def test_non_ew_mission_not_mistaken(self):
        m = Mission(name="diagonal")
        m.add_waypoint(lat=0.0, lon=0.0, alt=40)
        m.add_waypoint(lat=0.001, lon=0.001, alt=40)
        assert extract_ew_rows(m) == []
        res = coverage_ratio(m, _cam())
        assert res.get("error") and res["coverage_ratio"] == 0.0

    def test_coverage_dense_rows_full(self):
        # fp_across = 60 m at alt 40; lane gap 24 m => bands overlap heavily
        m = _area_mission(lat0=0.0, lon0=0.0, rows=3, gap_m=24.0)
        res = coverage_ratio(m, _cam())
        assert "error" not in res
        assert res["coverage_ratio"] == pytest.approx(1.0, abs=1e-6)

    def test_coverage_gap_matches_hand_value(self):
        # Two rows 70 m apart (fp=60 m) leaves a 10 m vertical gap inside the
        # bounding rectangle: theoretical coverage = 60/70 = 0.8571...
        m = _area_mission(lat0=0.0, lon0=0.0, rows=2, gap_m=70.0)
        res = coverage_ratio(m, _cam())
        assert "error" not in res
        assert res["coverage_ratio"] == pytest.approx(60.0 / 70.0, abs=0.02)

    def test_coverage_respects_altitude_footprint(self):
        cam = _cam()
        # higher altitude -> larger footprint -> full coverage
        m = _area_mission(lat0=0.0, lon0=0.0, rows=2, gap_m=70.0, alt=80.0)
        assert cam.footprint_across_m(80.0) == pytest.approx(120.0)
        res = coverage_ratio(m, cam)
        assert res["coverage_ratio"] > 0.99


# ----------------------------------------------------------------------
# survey grading
# ----------------------------------------------------------------------

class TestSurveyCheck:
    def test_pass_when_overlap_and_gsd_ok(self):
        m = _area_mission(lat0=0.0, lon0=0.0, rows=3, gap_m=24.0, alt=40.0)
        res = survey_check(m, _cam(), side_overlap=0.6, forward_overlap=0.7,
                           gsd_max_m=0.05)
        assert res["passed"] is True
        codes = [it["code"] for it in res["items"]]
        assert "gsd-ok" in codes
        assert "side-overlap-ok" in codes
        assert "coverage-ok" in codes
        assert not any(it["level"] == "error" for it in res["items"])

    def test_fail_on_wide_lane_spacing(self):
        # gap 50 m > theoretical 24 m -> side overlap ~17% << 60%
        m = _area_mission(lat0=0.0, lon0=0.0, rows=2, gap_m=50.0, alt=40.0)
        res = survey_check(m, _cam(), side_overlap=0.6)
        assert res["passed"] is False
        assert any(it["code"] == "side-overlap-low" and it["level"] == "error"
                   for it in res["items"])

    def test_fail_on_gsd_exceeded(self):
        m = _area_mission(lat0=0.0, lon0=0.0, rows=3, gap_m=24.0, alt=200.0)
        res = survey_check(m, _cam(), gsd_max_m=0.05)
        # at 200 m, p4rtk gsd = 200/40 * ~1.1 cm ~= 5.5 cm > 5 cm
        assert res["gsd_worst_cm"] > 5.0
        assert any(it["code"] == "gsd-exceeded" for it in res["items"])

    def test_forward_spacing_info_always_present(self):
        m = _area_mission(lat0=0.0, lon0=0.0, rows=3, gap_m=24.0)
        res = survey_check(m, _cam(), forward_overlap=0.7)
        assert any(it["code"] == "forward-spacing" and it["level"] == "info"
                   for it in res["items"])

    def test_empty_mission(self):
        res = survey_check(Mission(name="empty"), _cam())
        assert res["passed"] is False
        assert any(it["code"] == "empty-mission" for it in res["items"])


# ----------------------------------------------------------------------
# CLI smoke
# ----------------------------------------------------------------------

class TestCliV15:
    def test_survey_calc_output(self):
        res = CliRunner().invoke(
            __import__("mavplan.cli", fromlist=["main"]).main,
            ["survey", "calc", "--camera", "p4rtk", "--alt", "40"],
        )
        assert res.exit_code == 0, res.output
        assert "FOV" in res.output
        assert "GSD" in res.output
        assert "Recommended lane spacing" in res.output

    def test_survey_check_cli_and_html_report(self, tmp_path: Path):
        m = _area_mission(lat0=0.0, lon0=0.0, rows=3, gap_m=24.0)
        plan = tmp_path / "plan.json"
        report = tmp_path / "report.html"
        m.save(str(plan))
        res = CliRunner().invoke(
            __import__("mavplan.cli", fromlist=["main"]).main,
            ["survey", "check", str(plan), "--camera", "p4rtk",
             "--gsd-max", "0.05", "-o", str(report)],
        )
        assert res.exit_code == 0, res.output
        assert "判定：通过" in res.output
        text = report.read_text(encoding="utf-8")
        assert "测绘课程" in text
        assert "相机与重叠率" in text
        assert "地面分辨率（GSD）" in text
        assert "检查明细" in text

    def test_generate_lawnmower_camera_lane_spacing(self, tmp_path: Path):
        res = CliRunner().invoke(
            __import__("mavplan.cli", fromlist=["main"]).main,
            ["generate", "lawnmower",
             "--corner1", "0.0000,0.0000", "--corner2", "0.0010,0.0012",
             "--alt", "40", "--camera", "p4rtk", "--overlap-side", "0.6",
             "--no-save"],
        )
        assert res.exit_code == 0, res.output
        # lane spacing auto = 60*(1-0.6) = 24 m, so generated WPs are
        # ~24 m apart in latitude -> expect several lanes across 111 m
        assert "lane spacing auto = 24.0 m" in res.output
