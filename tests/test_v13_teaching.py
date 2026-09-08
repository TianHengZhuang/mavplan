"""v1.3 teaching suite tests: TaskSpec, task generation, grading engine,
HTML score report and the ``task`` CLI group.

These are the acceptance tests for the ROADMAP v1.3 milestone:
  - TaskSpec JSON model + geometry helpers;
  - deterministic task generation by difficulty (with gold routes that score
    100);
  - constraint-violation grading with Chinese comments (no-fly zone /
    missed checkpoint / window violations / time & distance limits);
  - self-contained HTML score report;
  - ``task`` CLI smoke commands.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mavplan.flightlog import FlightLog, FlightPoint
from mavplan.grade import grade_flight
from mavplan.mission import Mission
from mavplan.report_html import render_report
from mavplan.taskgen import generate_task
from mavplan.taskspec import (
    CheckPoint,
    TaskSpec,
    Zone,
    haversine_m,
    point_in_circle,
    segment_intersects_circle,
)

if True:  # noqa: E402 - CLI import needs package import side effects done
    from mavplan.cli import main
    from click.testing import CliRunner


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _sample_mission_flight(mission: Mission, sample_dt: float = 0.5) -> FlightLog:
    """Sample the waypoint route into a telemetry FlightLog (speed 10 m/s)."""
    wps = mission.waypoints()
    points: list[FlightPoint] = []
    t = 0.0
    for i in range(len(wps) - 1):
        a, b = wps[i], wps[i + 1]
        d = haversine_m(a.lat, a.lon, b.lat, b.lon)
        sp = max(b.speed, 0.1)
        n = max(3, int(d / sp / sample_dt))
        for k in range(1, n + 1):
            f = k / n
            points.append(FlightPoint(
                lat=a.lat + (b.lat - a.lat) * f,
                lon=a.lon + (b.lon - a.lon) * f,
                alt=a.alt + (b.alt - a.alt) * f,
                speed=sp,
                time_s=t + d / sp * f,
            ))
        t += d / sp
    return FlightLog(points=points)


def _manual_easy_spec() -> TaskSpec:
    """Small hand-built brief with 3 checkpoints around home."""
    home = (31.20, 121.40, 0.0)
    cps = [
        CheckPoint(name="A", lat=31.2030, lon=121.4030, radius_m=25.0),
        CheckPoint(name="B", lat=31.1990, lon=121.4060, radius_m=25.0),
        CheckPoint(name="C", lat=31.2040, lon=121.4100, radius_m=25.0),
    ]
    return TaskSpec(
        name="手写考核任务",
        description="飞越 A、B、C 三个航点后返航降落",
        difficulty="easy",
        home=home,
        required=cps,
        altitude_range=(40.0, 90.0),
        speed_range=(5.0, 15.0),
        max_time_s=600.0,
        max_distance_m=20000.0,
    )


def _manual_flight_via(via, cruise_alt: float = 60.0, cruise_speed: float = 10.0,
                       sample_dt: float = 0.5) -> FlightLog:
    """Build a FlightLog passing through ``via`` lat/lon points in order."""
    points: list[FlightPoint] = []
    t = 0.0
    prev = via[0]
    for cur in via[1:]:
        d = haversine_m(prev[0], prev[1], cur[0], cur[1])
        n = max(3, int(d / cruise_speed / sample_dt))
        for k in range(1, n + 1):
            f = k / n
            points.append(FlightPoint(
                lat=prev[0] + (cur[0] - prev[0]) * f,
                lon=prev[1] + (cur[1] - prev[1]) * f,
                alt=prev[2] if len(prev) > 2 else cruise_alt,
                speed=cruise_speed,
                time_s=t + d / cruise_speed * f,
            ))
        t += d / cruise_speed
        prev = cur
    return FlightLog(points=points)


def _cat_names(result) -> set[str]:
    return {d.category for d in result.deductions}


def _spec_difficulty_counts(spec: TaskSpec):
    return {
        "points": sum(1 for cp in spec.required if cp.kind == "point"),
        "areas": sum(1 for cp in spec.required if cp.kind == "area"),
        "zones": len(spec.no_fly_zones),
    }


# ----------------------------------------------------------------------
# TaskSpec model + geometry
# ----------------------------------------------------------------------

class TestTaskSpecModel:
    def test_json_roundtrip(self, tmp_path: Path):
        spec = _manual_easy_spec()
        spec.no_fly_zones = [Zone(name="测试禁飞区", lat=31.20, lon=121.40, radius_m=80.0)]
        path = tmp_path / "task.json"
        spec.save(str(path))

        loaded = TaskSpec.load(str(path))
        assert loaded.to_dict() == spec.to_dict()
        assert loaded.required_points() == loaded.required
        assert loaded.required_areas() == []
        assert loaded.no_fly_zones[0].name == "测试禁飞区"

    def test_validation_errors(self):
        bad = TaskSpec(
            altitude_range=(90.0, 40.0),  # inverted window
            speed_range=(15.0, 5.0),
            max_time_s=-1,
            max_distance_m=0,
            required=[CheckPoint(name="X", lat=999.0, lon=0, radius_m=0)],
        )
        errs = bad.validate()
        assert any("坐标非法" in e for e in errs)
        assert any("高度窗口下限大于上限" in e for e in errs)
        assert any("速度窗口下限大于上限" in e for e in errs)
        assert any("时间限制必须大于 0" in e for e in errs)
        assert any("距离限制必须大于 0" in e for e in errs)

    def test_json_contains_zone_and_limits(self, tmp_path: Path):
        spec = _manual_easy_spec()
        spec.no_fly_zones = [Zone(name="禁区", lat=31.2, lon=121.4, radius_m=50)]
        path = tmp_path / "task.json"
        spec.save(str(path))
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        assert raw["no_fly_zones"][0]["name"] == "禁区"
        assert raw["altitude_range"] == [40.0, 90.0]
        assert raw["max_distance_m"] > 0


class TestGeometry:
    def test_point_in_circle(self):
        assert point_in_circle(31.2, 121.4, 31.2, 121.4, 50.0)
        # ~111 m away > 50 m radius
        assert not point_in_circle(31.2010, 121.4, 31.2, 121.4, 50.0)

    def test_tangent_segment_not_entering(self):
        # Segment runs exactly along the boundary of the circle (tangent).
        # radius 50 m -> ~0.00045 deg of latitude at this scale.
        c_lat, c_lon = 31.2, 121.4
        r = 50.0
        # p1/p2 offset 50 m east/west of centre at the same latitude:
        # this line passes through the centre, so choose offset at radius+.
        deg_lat = r / 111_320.0
        # vertical tangent line: same lon as centre + tiny epsilon outside
        # compute east offset for 50 m at lat 31.2:
        import math
        dlon = r / (111_320.0 * math.cos(math.radians(c_lat)))
        # line at lon = c_lon + dlon (just east of circle) from lat- to lat+
        assert not segment_intersects_circle(
            c_lat - 0.005, c_lon + dlon + 1e-9,
            c_lat + 0.005, c_lon + dlon + 1e-9,
            c_lat, c_lon, r,
        )
        # chord through the circle definitely intersects
        assert segment_intersects_circle(
            c_lat - 0.005, c_lon - dlon,
            c_lat + 0.005, c_lon + dlon,
            c_lat, c_lon, r,
        )

    def test_segment_crossing_zone_is_detected(self):
        assert segment_intersects_circle(31.199, 121.4, 31.201, 121.4, 31.2, 121.4, 50.0)


# ----------------------------------------------------------------------
# task generation
# ----------------------------------------------------------------------

class TestTaskGeneration:
    @pytest.mark.parametrize("difficulty,min_pts,min_zones", [
        ("easy", 3, 0),
        ("medium", 4, 1),
        ("hard", 6, 2),
    ])
    def test_difficulty_scaling(self, difficulty, min_pts, min_zones):
        gen = generate_task(seed=7, difficulty=difficulty)
        counts = _spec_difficulty_counts(gen.spec)
        assert counts["points"] >= min_pts
        assert counts["zones"] >= min_zones
        assert gen.spec.validate() == []
        assert gen.gold_mission.waypoints(), "gold route must not be empty"

    def test_deterministic(self):
        a = generate_task(seed=2024, difficulty="medium")
        b = generate_task(seed=2024, difficulty="medium")
        assert a.spec.to_dict() == b.spec.to_dict()
        assert len(a.gold_mission.waypoints()) == len(b.gold_mission.waypoints())
        wps_a = [(w.lat, w.lon) for w in a.gold_mission.waypoints()]
        wps_b = [(w.lat, w.lon) for w in b.gold_mission.waypoints()]
        assert wps_a == wps_b

    def test_invalid_difficulty_raises(self):
        with pytest.raises(ValueError):
            generate_task(seed=1, difficulty="expert")

    @pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
    def test_gold_route_scores_100(self, difficulty):
        for seed in (1, 7, 42):
            gen = generate_task(seed=seed, difficulty=difficulty)
            flight = _sample_mission_flight(gen.gold_mission)
            result = grade_flight(gen.spec, flight, plan=gen.gold_mission, student="黄金样例")
            assert result.score == pytest.approx(100.0)
            assert result.deductions == []

    def test_gold_snapshot_counts_and_windows(self):
        # Snapshot test: fixed seed must keep its published numbers stable.
        gen = generate_task(seed=42, difficulty="hard")
        counts = _spec_difficulty_counts(gen.spec)
        assert counts == {"points": 6, "areas": 2, "zones": 3}
        assert gen.spec.altitude_range[0] <= gen.spec.altitude_range[1]
        assert gen.spec.speed_range[0] <= gen.spec.speed_range[1]
        assert gen.spec.max_time_s > 0
        assert gen.spec.max_distance_m > gen.gold_mission.total_distance()
        assert gen.spec.validate() == []


# ----------------------------------------------------------------------
# grading engine
# ----------------------------------------------------------------------

class TestGradingEngine:
    def test_perfect_manual_flight_full_score(self):
        spec = _manual_easy_spec()
        home = spec.home
        flight = _manual_flight_via([
            (home[0], home[1]),
            (spec.required[0].lat, spec.required[0].lon),
            (spec.required[1].lat, spec.required[1].lon),
            (spec.required[2].lat, spec.required[2].lon),
            (home[0], home[1]),
        ])
        result = grade_flight(spec, flight, student="张三")
        assert result.score == pytest.approx(100.0)
        assert result.passed
        assert result.level == "优秀"
        assert "成绩优秀" in result.comment

    def test_no_fly_zone_entry_deduction(self):
        gen = generate_task(seed=3, difficulty="medium")
        spec, gold = gen.spec, gen.gold_mission
        assert spec.no_fly_zones, "fixture expects a no-fly zone"
        zone = spec.no_fly_zones[0]

        # fly the gold order but detour through the zone centre mid-route
        wps = gold.waypoints()
        via = [(w.lat, w.lon) for w in wps]
        # insert zone centre after the first cruise waypoint
        via.insert(2, (zone.lat, zone.lon))
        flight = _manual_flight_via(via)
        result = grade_flight(spec, flight, plan=gold, student="李四")
        assert "no_fly_zone" in _cat_names(result)
        assert result.metrics["no_fly_zone_hits"]
        assert result.score == pytest.approx(80.0)

    def test_missed_checkpoint_deduction(self):
        spec = _manual_easy_spec()
        home = spec.home
        a, b, c = spec.required
        # Visit A and B but never approach C -> C is missed
        flight = _manual_flight_via([
            (home[0], home[1]),
            (a.lat, a.lon), (b.lat, b.lon),
            (home[0], home[1]),
        ])
        result = grade_flight(spec, flight, student="王五")
        assert "missed_checkpoint" in _cat_names(result)
        assert any("未到达必过航点「C」" in d.message for d in result.deductions)
        assert result.score == pytest.approx(85.0)

    def test_altitude_below_window_deduction(self):
        spec = _manual_easy_spec()
        home = spec.home
        flight = _manual_flight_via(
            [(home[0], home[1]),
             (spec.required[0].lat, spec.required[0].lon),
             (spec.required[1].lat, spec.required[1].lon),
             (spec.required[2].lat, spec.required[2].lon),
             (home[0], home[1])],
            cruise_alt=25.0,  # below 40 m window lower bound
        )
        result = grade_flight(spec, flight, student="赵六")
        assert "altitude_window" in _cat_names(result)
        assert result.score == pytest.approx(90.0)

    def test_speed_above_window_deduction(self):
        spec = _manual_easy_spec()
        home = spec.home
        flight = _manual_flight_via(
            [(home[0], home[1]),
             (spec.required[0].lat, spec.required[0].lon),
             (spec.required[1].lat, spec.required[1].lon),
             (spec.required[2].lat, spec.required[2].lon),
             (home[0], home[1])],
            cruise_speed=20.0,  # above 15 m/s window
        )
        result = grade_flight(spec, flight, student="钱七")
        assert "speed_window" in _cat_names(result)
        assert result.score == pytest.approx(90.0)

    def test_over_time_deduction(self):
        spec = _manual_easy_spec()
        spec.max_time_s = 60.0  # tighten the limit
        home = spec.home
        a, b, c = spec.required
        flight = _manual_flight_via([
            (home[0], home[1]),
            (a.lat, a.lon), (b.lat, b.lon), (c.lat, c.lon),
            (home[0], home[1]),
        ])
        # stretch time stamps to exceed the limit
        flight.points = [FlightPoint(p.lat, p.lon, p.alt, p.speed, p.time_s * 3.0, p.heading)
                         for p in flight.points]
        result = grade_flight(spec, flight, student="孙八")
        assert "over_time" in _cat_names(result)
        assert result.score == pytest.approx(90.0)

    def test_over_distance_deduction(self):
        spec = _manual_easy_spec()
        spec.max_distance_m = 1000.0  # tighter than the route length
        home = spec.home
        flight = _manual_flight_via([
            (home[0], home[1]),
            (spec.required[0].lat, spec.required[0].lon),
            (spec.required[1].lat, spec.required[1].lon),
            (spec.required[2].lat, spec.required[2].lon),
            (home[0], home[1]),
        ])
        result = grade_flight(spec, flight, student="周九")
        assert "over_distance" in _cat_names(result)
        assert result.score == pytest.approx(90.0)

    def test_multiple_violations_cap_at_zero(self):
        spec = _manual_easy_spec()
        # 6 independent required points, only the first is visited:
        # 5 missed (5x15) + no-fly entry (20) + time (10) + distance (10) > 100
        home = spec.home
        pts = [
            CheckPoint(name="P1", lat=31.2030, lon=121.4030, radius_m=25.0),
            CheckPoint(name="P2", lat=31.1990, lon=121.4060, radius_m=25.0),
            CheckPoint(name="P3", lat=31.2040, lon=121.4100, radius_m=25.0),
            CheckPoint(name="P4", lat=31.2060, lon=121.4020, radius_m=25.0),
            CheckPoint(name="P5", lat=31.1970, lon=121.4080, radius_m=25.0),
            CheckPoint(name="P6", lat=31.2050, lon=121.4150, radius_m=25.0),
        ]
        spec.required = pts
        spec.no_fly_zones = [Zone(name="考核禁区", lat=31.2015, lon=121.4015, radius_m=100.0)]
        spec.max_time_s = 1.0
        spec.max_distance_m = 1.0
        # home -> P1 crosses the zone halfway -> guaranteed zone entry
        flight = _manual_flight_via([(home[0], home[1]), (pts[0].lat, pts[0].lon)])
        result = grade_flight(spec, flight, student="吴十")
        assert result.score == pytest.approx(0.0)
        assert not result.passed
        assert result.level == "不合格"
        assert "不合格" in result.comment

    def test_grade_metrics_include_compare_when_plan_given(self):
        gen = generate_task(seed=42, difficulty="medium")
        flight = _sample_mission_flight(gen.gold_mission)
        result = grade_flight(gen.spec, flight, plan=gen.gold_mission, student="对比测试")
        assert "compare_to_plan" in result.metrics
        cmp = result.metrics["compare_to_plan"]
        assert cmp["waypoint_hits_50m"] >= 1

    def test_grade_metrics_without_plan(self):
        spec = _manual_easy_spec()
        home = spec.home
        flight = _manual_flight_via([(home[0], home[1]),
                                     (spec.required[0].lat, spec.required[0].lon),
                                     (home[0], home[1])])
        result = grade_flight(spec, flight)
        assert "compare_to_plan" not in result.metrics
        assert "total_distance_m" in result.metrics


# ----------------------------------------------------------------------
# HTML report
# ----------------------------------------------------------------------

class TestHtmlReport:
    def test_report_render_contains_core_fields(self, tmp_path: Path):
        gen = generate_task(seed=42, difficulty="medium")
        flight = _sample_mission_flight(gen.gold_mission)
        result = grade_flight(gen.spec, flight, plan=gen.gold_mission, student="演示学员")
        out = tmp_path / "report.html"
        html_doc = render_report(gen.spec, result, flight, plan=gen.gold_mission,
                                 output_path=str(out))

        assert out.exists()
        assert out.stat().st_size > 2000
        assert "航线规划考核 · 成绩报告" in html_doc
        assert "演示学员" in html_doc
        assert "扣分明细" in html_doc
        assert "<svg" in html_doc
        assert "禁飞区" in html_doc
        assert "优秀" in html_doc

    def test_report_render_with_deductions(self, tmp_path: Path):
        spec = _manual_easy_spec()
        home = spec.home
        flight = _manual_flight_via([(home[0], home[1]),
                                     (spec.required[0].lat, spec.required[0].lon),
                                     (spec.required[1].lat, spec.required[1].lon),
                                     (home[0], home[1])])
        result = grade_flight(spec, flight, student="有扣分学员")
        html_doc = render_report(spec, result, flight, output_path=str(tmp_path / "ded.html"))
        assert "未到达必过航点" in html_doc
        assert "-15" in html_doc


# ----------------------------------------------------------------------
# CLI task group
# ----------------------------------------------------------------------

class TestTaskCli:
    def _write_flight_csv(self, flight: FlightLog, path: Path) -> None:
        Path(path).write_text(flight.to_csv(), encoding="utf-8")

    def test_cli_generate_view_grade(self, tmp_path: Path):
        runner = CliRunner()
        task_json = str(tmp_path / "task.json")
        gold_json = str(tmp_path / "gold.json")
        flight_csv = str(tmp_path / "flight.csv")
        report_html = str(tmp_path / "report.html")

        res = runner.invoke(main, [
            "task", "generate", "--seed", "42", "--difficulty", "medium",
            "-o", task_json, "--plan-out", gold_json,
        ])
        assert res.exit_code == 0, res.output
        assert "Generated task" in res.output
        assert Path(task_json).exists()
        assert Path(gold_json).exists()

        res = runner.invoke(main, ["task", "view", task_json])
        assert res.exit_code == 0, res.output
        assert "航线规划考核" in res.output

        # build a flight CSV from the gold route, then grade it
        gold = Mission.load(gold_json)
        flight = _sample_mission_flight(gold)
        self._write_flight_csv(flight, Path(flight_csv))

        res = runner.invoke(main, [
            "task", "grade", task_json, flight_csv,
            "--plan", gold_json, "--student", "命令行学员", "-o", report_html,
        ])
        assert res.exit_code == 0, res.output
        assert "Score" in res.output
        assert Path(report_html).exists()
        text = Path(report_html).read_text(encoding="utf-8")
        assert "命令行学员" in text
        assert "成绩报告" in text

    def test_cli_view_invalid_task_errors(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"name": "bad", "altitude_range": [90, 40]}', encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(main, ["task", "view", str(bad)])
        assert res.exit_code != 0
