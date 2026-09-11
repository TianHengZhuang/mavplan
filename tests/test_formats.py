"""Tests for WPL / QGC .plan mission format interop."""
import json

import pytest

from mavplan import Mission, Waypoint
from mavplan.formats import (
    parse_qgc_plan,
    parse_wpl,
    save_qgc_plan,
    sniff_format,
    to_qgc_plan,
    to_wpl,
    load_mission_file,
)

WPL_SAMPLE = """QGC WPL 110
0\t1\t0\t16\t0\t0\t0\t0\t31.2300000\t121.4700000\t10.00
1\t0\t3\t16\t0\t2\t0\t-9999\t31.2300000\t121.4800000\t50.00
2\t0\t3\t16\t0\t2\t0\t-9999\t31.2400000\t121.4900000\t60.00
3\t0\t3\t178\t5\t0\t0\t0\t31.2400000\t121.4900000\t60.00
4\t0\t3\t16\t0\t2\t0\t-9999\t31.2500000\t121.5000000\t70.00
"""


def test_sniff_and_load_wpl_with_utf8_bom(tmp_path):
    """PowerShell ``Set-Content -Encoding utf8`` writes a BOM; loaders must accept it."""
    path = tmp_path / "mission.waypoints"
    path.write_text(WPL_SAMPLE, encoding="utf-8-sig")
    assert sniff_format(path) == "wpl"
    mission = load_mission_file(path)
    assert len(mission.waypoints()) == 4  # HOME row extracted


def test_sniff_qgc_plan_with_utf8_bom(tmp_path):
    path = tmp_path / "mission.plan"
    path.write_text(json.dumps(QGC_PLAN_SAMPLE), encoding="utf-8-sig")
    assert sniff_format(path) == "qgcplan"
    mission = load_mission_file(path)
    assert len(mission.waypoints()) >= 1


def test_sniff_raw_text_with_bom_prefix():
    assert sniff_format("﻿" + WPL_SAMPLE) == "wpl"

QGC_PLAN_SAMPLE = {
    "fileType": "Plan",
    "version": 1,
    "groundStation": "QGroundControl",
    "mission": {
        "cruiseSpeed": 15,
        "hoverSpeed": 5,
        "vehicleType": 2,
        "firmwareType": 12,
        "plannedHomePosition": [31.2, 121.4, 10.0],
        "items": [
            {
                "AMSLAltAboveTerrain": None,
                "Altitude": 50.0,
                "AltitudeMode": 1,
                "autoContinue": True,
                "command": 16,
                "doJumpId": None,
                "frame": 3,
                "params": [0.0, 2.0, 0.0, -9999.0, 31.230, 121.470, 50.0],
                "type": "SimpleItem",
                "coordinate": [31.230, 121.470],
            },
            {
                "AMSLAltAboveTerrain": None,
                "Altitude": 50.0,
                "AltitudeMode": 1,
                "autoContinue": True,
                "command": 206,
                "doJumpId": None,
                "frame": 3,
                "params": [25.0, 0.0, 0.0, 0.0, 31.230, 121.470, 50.0],
                "type": "SimpleItem",
                "coordinate": [31.230, 121.470],
            },
            {
                "AMSLAltAboveTerrain": None,
                "Altitude": 60.0,
                "AltitudeMode": 1,
                "autoContinue": True,
                "command": 16,
                "doJumpId": None,
                "frame": 3,
                "params": [0.0, 2.0, 0.0, -9999.0, 31.240, 121.490, 60.0],
                "type": "SimpleItem",
                "coordinate": [31.240, 121.490],
            },
        ],
    },
    "geoFence": {"circles": [], "polygons": [], "version": 1},
    "rallyPoints": {"points": [], "version": 1},
}


def make_mission() -> Mission:
    m = Mission(name="Test", home=(31.2, 121.4, 10.0))
    m.add_waypoint(lat=31.23, lon=121.47, alt=50, speed=10)
    m.add_waypoint(lat=31.24, lon=121.49, alt=60)
    return m


class TestSniffFormat:
    def test_wpl(self):
        assert sniff_format(WPL_SAMPLE) == "wpl"

    def test_qgcplan(self):
        assert sniff_format(json.dumps(QGC_PLAN_SAMPLE)) == "qgcplan"

    def test_mavplan_json(self):
        assert sniff_format(json.dumps({"name": "x", "waypoints": []})) == "mavplan"

    def test_garbage(self):
        assert sniff_format("hello world") is None


class TestParseWpl:
    def test_home_extracted(self):
        m = parse_wpl(WPL_SAMPLE)
        assert m.home == (31.23, 121.47, 10.0)

    def test_waypoints_parsed(self):
        m = parse_wpl(WPL_SAMPLE)
        assert len(m) == 4  # HOME excluded
        wps = m.waypoints()
        assert wps[0].lat == pytest.approx(31.23)
        assert wps[0].lon == pytest.approx(121.48)
        assert wps[0].command == 16
        assert wps[0].acceptance_radius == pytest.approx(2.0)
        assert wps[0].yaw == pytest.approx(-9999.0)

    def test_do_action_preserved(self):
        m = parse_wpl(WPL_SAMPLE)
        wps = m.waypoints()
        assert wps[2].command == 178  # DO_CHANGE_SPEED
        assert wps[2].delay == pytest.approx(5.0)  # param1 = speed

    def test_seq_renumbered(self):
        m = parse_wpl(WPL_SAMPLE)
        assert [wp.seq for wp in m.waypoints()] == [0, 1, 2, 3]

    def test_rejects_non_wpl(self):
        with pytest.raises(ValueError):
            parse_wpl("not a mission file\n1 2 3\n")


class TestWplRoundTrip:
    def test_roundtrip_preserves_items(self):
        m = make_mission()
        m.add_action(0, "DO_CHANGE_SPEED", param1=5.0)  # after WP0
        text = to_wpl(m)
        parsed = parse_wpl(text)
        assert parsed.home == pytest.approx((31.2, 121.4, 10.0))
        assert len(parsed) == len(m)
        for a, b in zip(parsed.waypoints(), m.waypoints()):
            assert a.lat == pytest.approx(b.lat, abs=1e-6)
            assert a.lon == pytest.approx(b.lon, abs=1e-6)
            assert a.alt == pytest.approx(b.alt)
            assert a.command == b.command
            assert a.delay == pytest.approx(b.delay, abs=1e-3)

    def test_no_home(self):
        m = Mission()
        m.add_waypoint(lat=31.23, lon=121.47, alt=50)
        text = to_wpl(m)
        parsed = parse_wpl(text)
        assert parsed.home is None
        assert len(parsed) == 1


class TestQgcPlan:
    def test_parse(self):
        m = parse_qgc_plan(json.dumps(QGC_PLAN_SAMPLE))
        assert m.home == (31.2, 121.4, 10.0)
        wps = m.waypoints()
        assert len(wps) == 3
        assert wps[0].lat == pytest.approx(31.230)
        assert wps[0].command == 16
        assert wps[1].command == 206  # DO_SET_CAM_TRIGG_DIST
        assert wps[1].delay == pytest.approx(25.0)  # param1
        assert wps[2].lon == pytest.approx(121.490)

    def test_rejects_non_plan(self):
        with pytest.raises(ValueError):
            parse_qgc_plan(json.dumps({"fileType": "Other"}))

    def test_to_plan_structure(self):
        m = make_mission()
        plan = to_qgc_plan(m)
        assert plan["fileType"] == "Plan"
        assert plan["mission"]["plannedHomePosition"] == [31.2, 121.4, 10.0]
        items = plan["mission"]["items"]
        assert len(items) == 2
        assert items[0]["params"] == [0.0, 2.0, 0.0, -9999.0, 31.23, 121.47, 50.0]
        assert items[0]["command"] == 16

    def test_plan_roundtrip(self, tmp_path):
        m = make_mission()
        m.add_camera_trigger("distance", 25.0, after_seq=0)
        p = tmp_path / "mission.plan"
        save_qgc_plan(m, p)
        loaded = load_mission_file(p)
        assert loaded.home == pytest.approx((31.2, 121.4, 10.0))
        assert len(loaded) == len(m)
        for a, b in zip(loaded.waypoints(), m.waypoints()):
            assert a.command == b.command
            assert a.lat == pytest.approx(b.lat, abs=1e-6)
            assert a.delay == pytest.approx(b.delay, abs=1e-6)


class TestLoadMissionFile:
    def test_load_wpl(self, tmp_path):
        p = tmp_path / "m.waypoints"
        p.write_text(WPL_SAMPLE, encoding="utf-8")
        m = load_mission_file(p)
        assert m.home == (31.23, 121.47, 10.0)
        assert len(m) == 4

    def test_load_qgcplan(self, tmp_path):
        p = tmp_path / "m.plan"
        p.write_text(json.dumps(QGC_PLAN_SAMPLE), encoding="utf-8")
        m = load_mission_file(p)
        assert len(m) == 3

    def test_load_mavplan(self, tmp_path):
        m = make_mission()
        p = tmp_path / "m.json"
        m.save(p)
        loaded = load_mission_file(p)
        assert len(loaded) == 2
        assert loaded.home == pytest.approx((31.2, 121.4, 10.0))

    def test_unrecognised(self, tmp_path):
        p = tmp_path / "x.txt"
        p.write_text("no format here", encoding="utf-8")
        with pytest.raises(ValueError):
            load_mission_file(p)
