"""Tests for mission preview and class summary HTML (v1.7)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from mavplan.mission import Mission
from mavplan.pattern import LawnMowerParams, StartCorner, generate_lawnmower
from mavplan.preview_html import render_mission_preview
from mavplan.taskspec import Zone
from mavplan.grade_batch import (
    ClassResult,
    StudentRow,
    render_class_summary_html,
    write_class_summary_html,
    batch_grade,
)


def _simple_mission() -> Mission:
    m = Mission(name="demo", home=(31.230, 121.470, 0.0))
    m.add_waypoint(lat=31.230, lon=121.470, alt=50)
    m.add_waypoint(lat=31.232, lon=121.470, alt=50)
    m.add_waypoint(lat=31.232, lon=121.475, alt=60)
    m.add_waypoint(lat=31.230, lon=121.475, alt=40)
    return m


class TestRenderMissionPreview:
    def test_renders_self_contained_html(self) -> None:
        doc = render_mission_preview(_simple_mission())
        assert doc.lstrip().startswith("<!DOCTYPE html>")
        assert "任务规划预览" in doc
        assert "id=\"map\"" in doc
        assert "id=\"profile\"" in doc
        assert "demo" in doc

    def test_includes_waypoint_sequence_numbers(self) -> None:
        doc = render_mission_preview(_simple_mission())
        assert 'data-seq="0"' in doc
        assert 'data-seq="3"' in doc

    def test_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "preview.html"
            doc = render_mission_preview(_simple_mission(), output_path=str(out))
            assert out.is_file()
            assert out.read_text(encoding="utf-8") == doc

    def test_overlays_no_fly_zones(self) -> None:
        zone = Zone(name="跑道", lat=31.231, lon=121.472, radius_m=80.0)
        doc = render_mission_preview(_simple_mission(), zones=[zone])
        assert "跑道" in doc
        assert "<circle" in doc

    def test_polygon_zone(self) -> None:
        zone = Zone(
            name="禁飞多边形",
            lat=31.231,
            lon=121.472,
            kind="polygon",
            vertices=[(31.230, 121.470), (31.232, 121.470), (31.232, 121.474)],
        )
        doc = render_mission_preview(_simple_mission(), zones=[zone])
        assert "禁飞多边形" in doc
        assert "<polygon" in doc

    def test_lawnmower_coverage_band(self) -> None:
        params = LawnMowerParams(
            corner1=(31.230, 121.470),
            corner2=(31.232, 121.475),
            altitude=50.0,
            lane_spacing=40.0,
            start_corner=StartCorner.SW,
        )
        mission = Mission(name="lawnmower")
        for wp in generate_lawnmower(params):
            mission.add_waypoint(
                lat=wp.lat, lon=wp.lon, alt=wp.alt, speed=wp.speed, command=wp.command
            )
        doc = render_mission_preview(mission)
        assert "覆盖带" in doc
        assert 'fill="#3498db"' in doc

    def test_empty_mission_raises_or_renders_message(self) -> None:
        # Mission with no waypoints should not crash.
        doc = render_mission_preview(Mission(name="empty"))
        assert "<!DOCTYPE html>" in doc

    def test_title_override(self) -> None:
        doc = render_mission_preview(_simple_mission(), title="课堂演示")
        assert "课堂演示" in doc

    def test_file_under_2mb_for_small_mission(self) -> None:
        doc = render_mission_preview(_simple_mission())
        assert len(doc.encode("utf-8")) < 2 * 1024 * 1024


class TestClassSummaryHtml:
    def _result(self) -> ClassResult:
        return ClassResult(
            task_name="矩形巡逻",
            pass_threshold=60.0,
            students=[
                StudentRow(
                    student_id="S001",
                    name="张三",
                    score=92.0,
                    passed=True,
                    status="ok",
                    deductions={"禁飞区": 20.0},
                    report_path="S001.html",
                ),
                StudentRow(
                    student_id="S002",
                    name="李四",
                    score=55.0,
                    passed=False,
                    status="ok",
                    deductions={"超时": 10.0, "漏点": 15.0},
                    report_path="S002.html",
                ),
                StudentRow(
                    student_id="S003",
                    name="王五",
                    status="skipped: no log file",
                ),
            ],
        )

    def test_renders_stats_and_rows(self) -> None:
        doc = render_class_summary_html(self._result())
        assert "班级成绩汇总" in doc
        assert "张三" in doc
        assert "李四" in doc
        assert "S001.html" in doc
        assert "优秀" in doc
        assert "不合格" in doc

    def test_write_class_summary_html(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            path = write_class_summary_html(self._result(), out)
            assert path.name == "class_summary.html"
            assert path.is_file()
            text = path.read_text(encoding="utf-8")
            assert "及格线" in text

    def test_batch_grade_writes_html(self) -> None:
        from mavplan.taskspec import TaskSpec, CheckPoint
        from mavplan.flightlog import FlightLog, FlightPoint
        import csv
        import json

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            logs = root / "logs"
            out = root / "out"
            logs.mkdir()
            out.mkdir()

            task = TaskSpec(
                name="t",
                home=(31.23, 121.47, 0.0),
                required=[CheckPoint(name="A", lat=31.231, lon=121.471, radius_m=50.0)],
                altitude_range=(30.0, 80.0),
                speed_range=(3.0, 15.0),
                max_time_s=600.0,
                max_distance_m=5000.0,
            )
            task_path = root / "task.json"
            task_path.write_text(json.dumps(task.to_dict()), encoding="utf-8")

            roster = root / "roster.csv"
            with open(roster, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(["student_id", "name"])
                w.writerow(["S001", "张三"])

            # Minimal valid CSV log near the required point.
            log = logs / "S001.csv"
            log.write_text(
                "lat,lon,alt,time_s,speed,heading\n"
                "31.2300,121.4700,50.0,0.0,10.0,90.0\n"
                "31.2310,121.4710,50.0,5.0,10.0,90.0\n"
                "31.2315,121.4715,50.0,10.0,10.0,90.0\n",
                encoding="utf-8",
            )

            result = batch_grade(roster, logs, task_path, out)
            assert (out / "class_summary.html").is_file()
            assert (out / "class_summary.csv").is_file()
            assert result.students[0].status == "ok"


class TestBomTolerantLoad:
    def test_mission_load_accepts_utf8_bom(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.json"
            payload = _simple_mission().to_dict()
            p.write_text(json.dumps(payload), encoding="utf-8-sig")
            m = Mission.load(p)
            assert len(m) == 4

    def test_zones_json_accepts_utf8_bom(self) -> None:
        from mavplan.nofly import load_zones_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "z.json"
            p.write_text(
                '[{"name":"跑道","kind":"circle","lat":31.231,"lon":121.472,"radius_m":80}]',
                encoding="utf-8-sig",
            )
            zones = load_zones_json(p)
            assert zones[0].name == "跑道"
