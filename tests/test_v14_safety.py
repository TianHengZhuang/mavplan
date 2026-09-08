"""v1.4 safety & verification tests: no-fly zones (circle/polygon),
``mission check`` preflight, lost-link teaching demo, and merging the
preflight section into the v1.3 score report.

Acceptance focus of the ROADMAP v1.4 milestone:
  - polygon/circle zone geometry unit tests, including boundary-tangent
    cases (a tangent path is NOT an entry, but is reported as a touch);
  - preflight returns a structured warning list (code / level / message);
  - KML import is reused to build no-fly zones;
  - CLI smoke for ``mission check`` and ``simulate lost-link``;
  - preflight section is embedded into the v1.3 HTML score report.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from mavplan.flightlog import FlightLog, FlightPoint
from mavplan.grade import grade_flight
from mavplan.mission import Mission
from mavplan.nofly import (
    PreflightParams,
    load_zones_from_kml,
    load_zones_json,
    preflight_check,
    preflight_summary,
)
from mavplan.report_html import render_report
from mavplan.simulate import (
    BatteryModel,
    LostLinkParams,
    SimulationParams,
    simulate_lost_link,
)
from mavplan.taskgen import generate_task
from mavplan.taskspec import (
    TaskSpec,
    Zone,
    point_in_polygon,
    segment_intersects_polygon,
)

if True:  # noqa: E402 - CLI import needs package import side effects done
    from mavplan.cli import main
    from click.testing import CliRunner


_M_PER_DEG = 111_320.0

# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _poly_square(center_lat: float, center_lon: float, half_deg: float = 0.001) -> list[tuple]:
    """Axis-aligned square ring around (center_lat, center_lon)."""
    return [
        (center_lat - half_deg, center_lon - half_deg),
        (center_lat + half_deg, center_lon - half_deg),
        (center_lat + half_deg, center_lon + half_deg),
        (center_lat - half_deg, center_lon + half_deg),
    ]


def _square_ring() -> list[tuple]:
    """Literal small square: lat 31.2000-31.2020, lon 121.4000-121.4020.

    Built from literals (not float arithmetic) so edge/vertex touch tests
    are exact.
    """
    return [
        (31.2000, 121.4000),
        (31.2020, 121.4000),
        (31.2020, 121.4020),
        (31.2000, 121.4020),
    ]


def _mission(wps: list[tuple]) -> Mission:
    """wps: (lat, lon[, alt[, speed]]) tuples -> Mission."""
    m = Mission()
    for wp in wps:
        lat, lon = wp[0], wp[1]
        alt = wp[2] if len(wp) > 2 else 50.0
        speed = wp[3] if len(wp) > 3 else 10.0
        m.add_waypoint(lat=lat, lon=lon, alt=alt, speed=speed)
    return m


def _codes(items) -> list[str]:
    return [it["code"] for it in items]


def _manual_brief(home=(31.20, 121.40, 0.0), zones=None) -> TaskSpec:
    return TaskSpec(
        name="v1.4 预检考核任务",
        description="多边形禁飞区判分验证",
        difficulty="medium",
        home=home,
        required=[],
        altitude_range=(40.0, 120.0),
        speed_range=(5.0, 15.0),
        max_time_s=900.0,
        max_distance_m=20000.0,
        no_fly_zones=zones or [],
    )


def _manual_flight_via(via, cruise_alt: float = 60.0, cruise_speed: float = 10.0) -> FlightLog:
    from mavplan.taskspec import haversine_m
    points: list[FlightPoint] = []
    t = 0.0
    for prev, cur in zip(via, via[1:]):
        d = haversine_m(prev[0], prev[1], cur[0], cur[1])
        n = max(3, int(d / cruise_speed / 0.5))
        for k in range(1, n + 1):
            f = k / n
            points.append(FlightPoint(
                lat=prev[0] + (cur[0] - prev[0]) * f,
                lon=prev[1] + (cur[1] - prev[1]) * f,
                alt=cruise_alt,
                speed=cruise_speed,
                time_s=t + d / cruise_speed * f,
            ))
        t += d / cruise_speed
    return FlightLog(points=points)


def _sample_mission_flight(mission: Mission, sample_dt: float = 0.5) -> FlightLog:
    """Sample the waypoint route into telemetry (10 m/s)."""
    from mavplan.taskspec import haversine_m
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


# ----------------------------------------------------------------------
# polygon geometry: point-in-polygon / segment intersection
# ----------------------------------------------------------------------

class TestPolygonGeometry:
    SQUARE = _square_ring()

    def test_point_inside_outside_and_boundary(self):
        assert point_in_polygon(31.2010, 121.4010, self.SQUARE)          # centre
        assert not point_in_polygon(31.2050, 121.4050, self.SQUARE)      # far outside
        # boundary edge / vertex are NOT "inside" (tangent semantics)
        assert not point_in_polygon(31.2010, 121.4000, self.SQUARE)      # edge point
        assert not point_in_polygon(31.2000, 121.4000, self.SQUARE)      # vertex point

    def test_segment_crossing_polygon_is_detected(self):
        # south -> north through the square interior
        assert segment_intersects_polygon(
            31.1990, 121.4010, 31.2030, 121.4010, self.SQUARE)

    def test_segment_touching_boundary_is_not_an_entry(self):
        # endpoint sits exactly on the bottom edge (lat 31.2000), the
        # rest of the segment stays south of the polygon
        assert not segment_intersects_polygon(
            31.1990, 121.4010, 31.2000, 121.4010, self.SQUARE)


# ----------------------------------------------------------------------
# preflight engine (structured warning list)
# ----------------------------------------------------------------------

class TestPreflight:
    def test_clean_mission_no_warnings(self):
        m = _mission([
            (31.2000, 121.4000), (31.2010, 121.4010), (31.2000, 121.4000),
        ])
        items = preflight_check(m, zones=[])
        assert items == []
        assert preflight_summary(items) == {"errors": 0, "warnings": 0, "info": 0}

    def test_max_distance_and_altitude(self):
        m = _mission([
            (31.20000, 121.40000),  # home
            (31.20500, 121.40000, 150.0),  # 556 m away, 150 m high
        ])
        items = preflight_check(m, zones=[])
        codes = _codes(items)
        assert "max_distance" in codes
        assert "max_altitude" in codes
        dist = [it for it in items if it["code"] == "max_distance"][0]
        alt = [it for it in items if it["code"] == "max_altitude"][0]
        assert dist["level"] == "error" and alt["level"] == "error"
        assert "超过最大允许距离" in dist["message"]
        assert "超过最大允许高度" in alt["message"]

    def test_turn_radius_and_bank_warning(self):
        # three waypoints forming a tight 90-degree turn (~15 m legs)
        dlat = 15.0 / _M_PER_DEG
        dlon = 15.0 / (_M_PER_DEG * math.cos(math.radians(31.2)))
        w1 = (31.2000, 121.4000)
        w2 = (w1[0] + dlat, w1[1])
        w3 = (w2[0], w2[1] + dlon)
        m = _mission([w1, w2, w3])
        items = preflight_check(m, zones=[])
        codes = _codes(items)
        assert "turn_radius" in codes, codes
        assert "bank_angle" in codes, codes
        tr = [it for it in items if it["code"] == "turn_radius"][0]
        bk = [it for it in items if it["code"] == "bank_angle"][0]
        assert tr["level"] == "error"
        assert bk["level"] == "warning"
        assert "转弯半径" in tr["message"]
        assert "坡度" in bk["message"]

    def test_circle_entry_detected(self):
        zone = Zone(name="机场保护区", lat=31.2000, lon=121.4000, radius_m=60.0)
        m = _mission([(31.2000, 121.3990), (31.2000, 121.4010)])
        items = preflight_check(m, zones=[zone])
        codes = _codes(items)
        assert "no_fly_enter" in codes, codes
        msg = [it for it in items if it["code"] == "no_fly_enter"][0]["message"]
        assert "机场保护区" in msg

    def test_circle_tangent_is_touch_not_entry(self):
        # straight leg runs exactly along the 50 m tangent line north of
        # the circle centre: closest approach == radius.
        zone = Zone(name="塔台", lat=31.2000, lon=121.4000, radius_m=50.0)
        dlat = 50.0 / _M_PER_DEG
        m = _mission([
            (31.2000 + dlat, 121.3990),
            (31.2000 + dlat, 121.4010),
        ])
        items = preflight_check(m, zones=[zone])
        codes = _codes(items)
        assert "no_fly_touch" in codes, codes
        assert "no_fly_enter" not in codes, codes

    def test_polygon_entry_and_boundary_touch(self):
        ring = _square_ring()
        zone = Zone(name="限飞区", lat=31.2010, lon=121.4010, kind="polygon",
                    vertices=ring)
        # crossing through the square interior -> entry error
        m_enter = _mission([
            (31.1990, 121.4010), (31.2030, 121.4010),
        ])
        items = preflight_check(m_enter, zones=[zone])
        codes = _codes(items)
        assert "no_fly_enter" in codes, codes
        assert "no_fly_touch" not in codes

        # endpoint exactly on the bottom edge (lat 31.2000) -> tangent only
        m_touch = _mission([
            (31.1995, 121.4010), (31.2000, 121.4010),
        ])
        items = preflight_check(m_touch, zones=[zone])
        codes = _codes(items)
        assert "no_fly_touch" in codes, codes
        assert "no_fly_enter" not in codes, codes

    def test_battery_infeasible_error(self):
        m = _mission([(31.2000, 121.4000), (31.20005, 121.4000)])
        tiny = BatteryModel(capacity_mah=100.0, voltage=22.2)
        items = preflight_check(m, zones=[], params=PreflightParams(battery=tiny))
        codes = _codes(items)
        assert "battery_energy" in codes, codes
        it = [x for x in items if x["code"] == "battery_energy"][0]
        assert it["level"] == "error"
        assert "电池余量不足" in it["message"]

    def test_battery_reserve_warning(self):
        # straight ~4.9 km route: feasible on the default pack but the
        # remaining margin drops below the requested 20 % reserve.
        pts = [(31.2000 + i * 0.011, 121.4000) for i in range(5)]
        m = _mission(pts)
        items = preflight_check(m, zones=[],
                                params=PreflightParams(max_distance_m=20000.0))
        codes = _codes(items)
        assert "battery_reserve" in codes, codes
        assert "battery_energy" not in codes

    def test_summary_counts(self):
        m = _mission([(31.20000, 121.40000), (31.20500, 121.40000, 150.0)])
        items = preflight_check(m, zones=[])
        s = preflight_summary(items)
        assert s["errors"] >= 2
        assert s["warnings"] >= 0


# ----------------------------------------------------------------------
# zone loading (KML reuse + JSON)
# ----------------------------------------------------------------------

class TestZoneLoading:
    def test_kml_polygon_and_point(self, tmp_path: Path):
        kml = tmp_path / "zones.kml"
        kml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>教学楼</name>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        121.4000,31.2010,0 121.4020,31.2010,0 121.4020,31.2030,0 121.4000,31.2010,0
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
    <Placemark><name>信号塔</name><Point><coordinates>121.4100,31.2050,0</coordinates></Point></Placemark>
  </Document>
</kml>""", encoding="utf-8")
        zones = load_zones_from_kml(str(kml), circle_radius_m=80.0)
        assert len(zones) == 2
        poly = zones[0]
        assert poly.kind == "polygon"
        assert poly.name == "教学楼"
        # closing duplicate is removed: 4 coords -> 3-ring vertices
        assert len(poly.polygon_ring()) == 3
        assert poly.validate() == []
        pt = zones[1]
        assert pt.kind == "circle"
        assert pt.name == "信号塔"
        assert pt.radius_m == pytest.approx(80.0)

    def test_kml_without_zones_raises(self, tmp_path: Path):
        kml = tmp_path / "empty.kml"
        kml.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>',
                       encoding="utf-8")
        with pytest.raises(ValueError):
            load_zones_from_kml(str(kml))

    def test_json_zones_roundtrip_and_invalid(self, tmp_path: Path):
        ring = _poly_square(31.2010, 121.4010, half_deg=0.001)
        zone = Zone(name="演示禁区", lat=31.2010, lon=121.4010, kind="polygon",
                    vertices=ring)
        data = zone.to_dict()
        path = tmp_path / "zones.json"
        path.write_text(json.dumps({"zones": [data]}, ensure_ascii=False), encoding="utf-8")
        loaded = load_zones_json(str(path))
        assert len(loaded) == 1
        assert loaded[0].kind == "polygon"
        assert loaded[0].name == "演示禁区"
        assert loaded[0].validate() == []

        # single zone dict layout
        single = tmp_path / "single.json"
        single.write_text(json.dumps(zone.to_dict()), encoding="utf-8")
        assert len(load_zones_json(str(single))) == 1

        bad = tmp_path / "bad.json"
        bad.write_text('{"kind": "circle", "lat": 91.0, "lon": 121.4, "radius_m": 10}',
                       encoding="utf-8")
        with pytest.raises(ValueError):
            load_zones_json(str(bad))


# ----------------------------------------------------------------------
# grading: polygon no-fly zones reuse the tangent semantics
# ----------------------------------------------------------------------

class TestPolygonGrading:
    # big literal square: lat 31.2000-31.2040, lon 121.4000-121.4040
    ZONE_RING = [
        (31.2000, 121.4000),
        (31.2040, 121.4000),
        (31.2040, 121.4040),
        (31.2000, 121.4040),
    ]

    def test_entry_into_polygon_zone_deducts(self):
        spec = _manual_brief(zones=[
            Zone(name="多边形禁区", lat=31.2020, lon=121.4020, kind="polygon",
                 vertices=self.ZONE_RING),
        ])
        flight = _manual_flight_via([
            (31.1990, 121.4010), (31.2050, 121.4010), (31.1990, 121.4010),
        ])
        result = grade_flight(spec, flight, student="多边形闯入")
        assert any(d.category == "no_fly_zone" for d in result.deductions)
        assert result.metrics.get("no_fly_zone_hits")

    def test_boundary_tangent_does_not_deduct(self):
        spec = _manual_brief(zones=[
            Zone(name="多边形禁区", lat=31.2020, lon=121.4020, kind="polygon",
                 vertices=self.ZONE_RING),
        ])
        # bottom edge of the square is lat = 31.2000; the route only
        # touches that boundary point from the south and returns.
        flight = _manual_flight_via([
            (31.1990, 121.4010), (31.2000, 121.4010), (31.1990, 121.4010),
        ])
        result = grade_flight(spec, flight, student="贴边不罚")
        assert result.deductions == []
        assert not result.metrics.get("no_fly_zone_hits")


# ----------------------------------------------------------------------
# lost-link teaching demo
# ----------------------------------------------------------------------

class TestLostLink:
    def _route(self) -> Mission:
        return _mission([
            (31.2000, 121.4000),
            (31.2020, 121.4010),
            (31.2030, 121.3990),
            (31.2010, 121.4000),
        ])

    def test_rtl_events_sequence(self):
        m = self._route()
        events = simulate_lost_link(m)
        types = [ev["type"] for ev in events]
        assert "link_lost" in types
        assert "policy" in types
        assert "rtl_route" in types
        assert "rtl_estimate" in types
        assert "battery" in types
        assert "teaching" in types
        joined = "\n".join(ev["message"] for ev in events)
        assert "自动返航" in joined
        assert "直飞返航点" in joined
        assert "电量" in joined
        # events carry seq + time metadata
        first = events[0]
        assert first["seq"] == 1
        assert first["time_s"] >= 0

    def test_hold_policy_skips_rtl(self):
        m = self._route()
        link = LostLinkParams(lost_at_s=10.0, fail_safe="hold")
        events = simulate_lost_link(m, SimulationParams(), link)
        types = [ev["type"] for ev in events]
        assert "rtl_route" not in types
        assert "battery" not in types
        assert any("原地悬停" in ev["message"] for ev in events if ev["type"] == "policy")

    def test_continue_policy_message(self):
        m = self._route()
        link = LostLinkParams(lost_at_s=10.0, fail_safe="continue")
        events = simulate_lost_link(m, SimulationParams(), link)
        types = [ev["type"] for ev in events]
        assert "rtl_route" not in types
        assert any("继续执行" in ev["message"] for ev in events if ev["type"] == "policy")

    def test_tiny_battery_flags_rtl_risk(self):
        m = self._route()
        sim = SimulationParams(battery=BatteryModel(capacity_mah=100.0, voltage=22.2))
        events = simulate_lost_link(m, sim, LostLinkParams(lost_at_s=10.0))
        bat = [ev for ev in events if ev["type"] == "battery"]
        assert bat
        assert "不足" in bat[0]["message"]


# ----------------------------------------------------------------------
# v1.4 merged into the v1.3 score report
# ----------------------------------------------------------------------

class TestReportPreflightSection:
    def test_report_renders_preflight_clean(self, tmp_path: Path):
        gen = generate_task(seed=42, difficulty="medium")
        flight = _sample_mission_flight(gen.gold_mission)
        result = grade_flight(gen.spec, flight, plan=gen.gold_mission, student="预检学员")

        items = preflight_check(gen.gold_mission, gen.spec.no_fly_zones,
                                PreflightParams(
                                    max_distance_m=gen.spec.max_distance_m,
                                    max_altitude_m=gen.spec.altitude_range[1],
                                    cruise_speed=float(gen.spec.speed_range[1]),
                                ))
        out = tmp_path / "report.html"
        html_doc = render_report(gen.spec, result, flight, plan=gen.gold_mission,
                                 output_path=str(out), preflight_items=items)
        assert "飞行前安全预检" in html_doc
        assert ("预检全部通过" in html_doc) or ("<tbody>" in html_doc)

    def test_report_shows_warning_rows(self, tmp_path: Path):
        spec = _manual_brief(zones=[Zone(name="机场", lat=31.2, lon=121.4, radius_m=60)])
        m = _mission([(31.2000, 121.3990), (31.2000, 121.4010)])
        items = preflight_check(m, zones=spec.no_fly_zones)
        assert any(it["code"] == "no_fly_enter" for it in items)

        home = spec.home
        flight = _manual_flight_via([(home[0], home[1]), (31.2000, 121.4010),
                                     (home[0], home[1])])
        result = grade_flight(spec, flight, student="告警展示")
        html_doc = render_report(spec, result, flight, output_path=str(tmp_path / "w.html"),
                                 preflight_items=items)
        assert "飞行前安全预检" in html_doc
        assert "no_fly_enter" in html_doc


# ----------------------------------------------------------------------
# CLI smoke
# ----------------------------------------------------------------------

class TestCliV14:
    def _write_mission(self, path: Path, wps) -> Mission:
        m = _mission(wps)
        m.save(str(path))
        return m

    def test_mission_check_clean(self, tmp_path: Path):
        p = tmp_path / "clean.json"
        self._write_mission(p, [(31.2000, 121.4000), (31.2010, 121.4010)])
        res = CliRunner().invoke(main, ["mission", "check", str(p)])
        assert res.exit_code == 0, res.output
        assert "All safety checks passed" in res.output

    def test_mission_check_alerts_with_zones(self, tmp_path: Path):
        p = tmp_path / "far.json"
        self._write_mission(p, [(31.20000, 121.40000), (31.20500, 121.40000, 150.0)])
        # square crossing the route at lon 121.4000: lat 31.199-31.203,
        # lon 121.399-121.401 (route enters the interior)
        ring = [
            (31.1990, 121.3990),
            (31.2030, 121.3990),
            (31.2030, 121.4010),
            (31.1990, 121.4010),
        ]
        zone = Zone(name="教学楼", lat=31.2010, lon=121.4000, kind="polygon",
                    vertices=ring)
        zf = tmp_path / "zones.json"
        zf.write_text(json.dumps([zone.to_dict()], ensure_ascii=False), encoding="utf-8")

        res = CliRunner().invoke(main, [
            "mission", "check", str(p), "--zones-json", str(zf),
            "--max-distance", "500", "--max-altitude", "120",
        ])
        assert res.exit_code == 0, res.output
        assert "[ERROR]" in res.output
        assert "Summary: " in res.output
        assert "超过最大允许距离" in res.output

    def test_simulate_lost_link_cli(self, tmp_path: Path):
        p = tmp_path / "route.json"
        m = _mission([
            (31.2000, 121.4000), (31.2020, 121.4010),
            (31.2030, 121.3990), (31.2010, 121.4000),
        ])
        m.save(str(p))
        res = CliRunner().invoke(main, [
            "simulate", "lost-link", str(p), "--lost-at", "20", "--fail-safe", "rtl",
        ])
        assert res.exit_code == 0, res.output
        assert "[link_lost]" in res.output
        assert "[rtl_route]" in res.output
        assert "[teaching]" in res.output

    def test_task_grade_merges_preflight(self, tmp_path: Path):
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

        gold = Mission.load(gold_json)
        flight = _sample_mission_flight(gold)
        Path(flight_csv).write_text(flight.to_csv(), encoding="utf-8")

        res = runner.invoke(main, [
            "task", "grade", task_json, flight_csv,
            "--plan", gold_json, "--student", "预检学员", "-o", report_html,
        ])
        assert res.exit_code == 0, res.output
        assert "Preflight" in res.output
        text = Path(report_html).read_text(encoding="utf-8")
        assert "飞行前安全预检" in text
