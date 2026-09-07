"""Tests for mavplan."""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from mavplan import Mission, Waypoint
from mavplan.pattern import (
    LawnMowerParams,
    PolygonScanParams,
    OrbitParams,
    StartCorner,
    generate_lawnmower,
    generate_polygon_scan,
    generate_orbit,
)
from mavplan.flightlog import (
    FlightLog,
    FlightPoint,
    FlightStats,
    parse_csv,
    compare_to_plan,
)
from mavplan.kml_import import (
    KmlDocument,
    KmlWaypoint,
    parse_kml,
    get_templates,
    MissionTemplate,
)
from mavplan.mavlink_link import (
    MAVLinkConnection,
    ConnectionState,
    HeartbeatInfo,
)


class TestWaypoint:
    def test_create(self):
        wp = Waypoint(lat=31.23, lon=121.47, alt=50.0, speed=10.0)
        assert wp.lat == 31.23
        assert wp.lon == 121.47
        assert wp.alt == 50.0
        assert wp.speed == 10.0
        assert wp.seq == 0

    def test_validate_lat_out_of_range(self):
        wp = Waypoint(lat=95.0, lon=121.47, alt=50.0)
        assert "Latitude 95.0 is out of range" in wp.validate()

    def test_validate_lon_out_of_range(self):
        wp = Waypoint(lat=31.23, lon=200.0, alt=50.0)
        assert "Longitude 200.0 is out of range" in wp.validate()

    def test_validate_alt_unsafe(self):
        wp = Waypoint(lat=31.23, lon=121.47, alt=-5000.0)
        assert any("Altitude" in e for e in wp.validate())

    def test_validate_ok(self):
        wp = Waypoint(lat=31.23, lon=121.47, alt=50.0)
        assert wp.validate() == []

    def test_distance_to(self):
        wp1 = Waypoint(lat=31.23, lon=121.47, alt=50.0)
        wp2 = Waypoint(lat=31.24, lon=121.48, alt=50.0)
        dist = wp1.distance_to(wp2)
        # ~1.4km at this latitude
        assert 1300 < dist < 1500

    def test_bearing_to(self):
        wp1 = Waypoint(lat=0.0, lon=0.0, alt=50.0)
        wp2 = Waypoint(lat=0.0, lon=1.0, alt=50.0)
        bearing = wp1.bearing_to(wp2)
        assert 85 < bearing < 95  # roughly east

    def test_to_mavlink_item(self):
        wp = Waypoint(lat=31.23, lon=121.47, alt=50.0, speed=10.0, delay=5.0, yaw=90.0)
        item = wp.to_mavlink_item()
        assert item["x"] == 31.23
        assert item["y"] == 121.47
        assert item["z"] == 50.0
        assert item["param1"] == 5.0  # delay
        assert item["param4"] == 90.0  # yaw

    def test_to_dict_roundtrip(self):
        wp = Waypoint(lat=31.23, lon=121.47, alt=50.0, speed=10.0)
        data = wp.to_dict()
        restored = Waypoint.from_dict(data)
        assert restored.lat == wp.lat
        assert restored.lon == wp.lon
        assert restored.alt == wp.alt
        assert restored.speed == wp.speed


class TestMission:
    def test_create(self):
        m = Mission(name="Test")
        assert m.name == "Test"
        assert len(m) == 0

    def test_add_waypoint_auto_seq(self):
        m = Mission()
        wp1 = m.add_waypoint(lat=31.23, lon=121.47, alt=50.0)
        wp2 = m.add_waypoint(lat=31.24, lon=121.48, alt=50.0)
        assert wp1.seq == 0
        assert wp2.seq == 1

    def test_validate_empty(self):
        m = Mission()
        errors = m.validate()
        assert "no waypoints" in errors[0]

    def test_validate_ok(self):
        m = Mission()
        m.add_waypoint(lat=31.23, lon=121.47, alt=50.0)
        m.add_waypoint(lat=31.24, lon=121.48, alt=50.0)
        assert m.validate() == []

    def test_total_distance(self):
        m = Mission()
        m.add_waypoint(lat=31.23, lon=121.47, alt=50.0)
        m.add_waypoint(lat=31.24, lon=121.48, alt=50.0)
        dist = m.total_distance()
        assert dist > 0

    def test_estimated_duration(self):
        m = Mission()
        m.add_waypoint(lat=31.23, lon=121.47, alt=50.0)
        m.add_waypoint(lat=31.24, lon=121.48, alt=50.0)
        dur = m.estimated_duration()
        assert dur > 0

    def test_to_mavlink_format(self):
        m = Mission()
        m.add_waypoint(lat=31.23, lon=121.47, alt=50.0)
        m.add_waypoint(lat=31.24, lon=121.48, alt=60.0)
        out = m.to_mavlink()
        lines = out.splitlines()
        assert lines[0] == "QGC WPL 120"
        assert len(lines) == 3  # header + 2 waypoints

    def test_to_kml_contains_waypoints(self):
        m = Mission()
        m.add_waypoint(lat=31.23, lon=121.47, alt=50.0)
        m.add_waypoint(lat=31.24, lon=121.48, alt=60.0)
        out = m.to_kml()
        assert "<kml" in out
        assert "<Placemark>" in out
        assert "<LineString>" in out
        assert "31.2300" in out

    def test_to_csv_contains_header(self):
        m = Mission()
        m.add_waypoint(lat=31.23, lon=121.47, alt=50.0)
        out = m.to_csv()
        assert "seq\tlat\tlon\talt" in out
        assert "0\t31.2300" in out

    def test_to_dict_roundtrip(self):
        m = Mission(name="Survey")
        m.add_waypoint(lat=31.23, lon=121.47, alt=50.0)
        data = m.to_dict()
        restored = Mission.from_dict(data)
        assert restored.name == "Survey"
        assert len(restored) == 1
        assert restored[0].lat == 31.23


class TestLawnMowerPattern:
    def test_generates_even_number_of_waypoints(self):
        params = LawnMowerParams(
            corner1=(31.230, 121.470),
            corner2=(31.240, 121.480),
            altitude=50.0,
            lane_spacing=20.0,
        )
        wps = list(generate_lawnmower(params))
        # Should be multiple of 2 (each lane has 2 waypoints)
        assert len(wps) % 2 == 0
        assert len(wps) >= 2

    def test_waypoints_alternate_lon_direction(self):
        params = LawnMowerParams(
            corner1=(31.230, 121.470),
            corner2=(31.240, 121.480),
            altitude=50.0,
            lane_spacing=20.0,
        )
        wps = list(generate_lawnmower(params))
        for i in range(0, len(wps) - 1, 2):
            # Even indices: sweep start, odd: sweep end
            assert wps[i].lon < wps[i + 1].lon

    def test_all_waypoints_in_bbox(self):
        params = LawnMowerParams(
            corner1=(31.230, 121.470),
            corner2=(31.240, 121.480),
            altitude=50.0,
            lane_spacing=20.0,
        )
        wps = list(generate_lawnmower(params))
        min_lat = min(31.230, 31.240)
        max_lat = max(31.230, 31.240)
        min_lon = min(121.470, 121.480)
        max_lon = max(121.470, 121.480)
        for wp in wps:
            assert min_lat <= wp.lat <= max_lat
            assert min_lon <= wp.lon <= max_lon

    def test_invalid_lane_spacing_raises(self):
        params = LawnMowerParams(
            corner1=(31.230, 121.470),
            corner2=(31.240, 121.480),
            altitude=50.0,
            lane_spacing=-10.0,
        )
        with pytest.raises(ValueError, match="Invalid"):
            list(generate_lawnmower(params))

    def test_start_from_outer_vs_inner(self):
        params_outer = LawnMowerParams(
            corner1=(31.230, 121.470),
            corner2=(31.240, 121.480),
            altitude=50.0,
            lane_spacing=20.0,
            start_from_outer=True,
        )
        params_inner = LawnMowerParams(
            corner1=(31.230, 121.470),
            corner2=(31.240, 121.480),
            altitude=50.0,
            lane_spacing=20.0,
            start_from_outer=False,
        )
        wps_outer = list(generate_lawnmower(params_outer))
        wps_inner = list(generate_lawnmower(params_inner))
        # Both produce same count, just different order
        assert len(wps_outer) == len(wps_inner)


class TestOrbitPattern:
    def test_generates_requested_num_points(self):
        params = OrbitParams(
            center_lat=31.235, center_lon=121.475,
            radius=50.0, altitude=50.0, num_points=8,
        )
        wps = list(generate_orbit(params))
        assert len(wps) == 8

    def test_all_waypoints_same_altitude(self):
        params = OrbitParams(
            center_lat=31.235, center_lon=121.475,
            radius=50.0, altitude=50.0, num_points=12,
        )
        wps = list(generate_orbit(params))
        for wp in wps:
            assert wp.alt == 50.0

    def test_waypoints_circular_distribution(self):
        params = OrbitParams(
            center_lat=31.235, center_lon=121.475,
            radius=50.0, altitude=50.0, num_points=12,
        )
        wps = list(generate_orbit(params))
        # All waypoints should be roughly equidistant from center
        for wp in wps:
            lat_diff = abs(wp.lat - params.center_lat)
            lon_diff = abs(wp.lon - params.center_lon)
            # Very rough check (within ~100m)
            assert lat_diff < 0.001
            assert lon_diff < 0.001

    def test_invalid_num_points_raises(self):
        params = OrbitParams(
            center_lat=31.235, center_lon=121.475,
            radius=50.0, altitude=50.0, num_points=2,
        )
        with pytest.raises(ValueError, match="Invalid"):
            list(generate_orbit(params))


class TestPolygonScan:
    def test_rectangle_polygon_generates_waypoints(self):
        rect = [(31.230, 121.470), (31.240, 121.470), (31.240, 121.480), (31.230, 121.480)]
        params = PolygonScanParams(
            polygon=rect, altitude=50.0, lane_spacing=20.0,
        )
        wps = list(generate_polygon_scan(params))
        assert len(wps) >= 2
        for wp in wps:
            assert -90 <= wp.lat <= 90
            assert -180 <= wp.lon <= 180

    def test_polygon_validation_rejects_small(self):
        params = PolygonScanParams(
            polygon=[(31.23, 121.47), (31.24, 121.48)],
            altitude=50.0, lane_spacing=20.0,
        )
        errors = params.validate()
        assert any("at least 3" in e for e in errors)


class TestFlightLog:
    def test_flight_point_distance(self):
        # Two points ~111m apart in latitude
        p1 = FlightPoint(lat=31.0, lon=121.0, alt=50.0)
        p2 = FlightPoint(lat=31.001, lon=121.0, alt=50.0)
        dist = p1.distance_to(p2)
        assert 100 < dist < 120  # ~111m at this latitude

    def test_flight_stats_empty(self):
        log = FlightLog(points=[], source_file="test.csv")
        s = log.stats()
        assert s.total_distance_m == 0
        assert s.num_points == 0
        assert s.flight_duration_s == 0

    def test_flight_stats_basic(self):
        points = [
            FlightPoint(lat=31.230, lon=121.470, alt=50.0, speed=10.0, time_s=0.0),
            FlightPoint(lat=31.231, lon=121.471, alt=55.0, speed=10.0, time_s=10.0),
            FlightPoint(lat=31.232, lon=121.472, alt=60.0, speed=10.0, time_s=20.0),
        ]
        log = FlightLog(points=points, source_file="test.csv")
        s = log.stats()
        assert s.num_points == 3
        assert s.total_distance_m > 0
        assert s.max_altitude_m == 60.0
        assert s.min_altitude_m == 50.0
        assert s.max_altitude_change_m == 10.0
        assert s.avg_speed_mps == 10.0
        assert s.flight_duration_s == 20.0

    def test_flight_log_to_kml(self):
        points = [
            FlightPoint(lat=31.23, lon=121.47, alt=50.0, time_s=0.0),
            FlightPoint(lat=31.24, lon=121.48, alt=50.0, time_s=10.0),
        ]
        log = FlightLog(points=points)
        kml = log.to_kml(name="Test Flight")
        assert "<kml" in kml
        assert "Flight Path" in kml
        assert "31.23" in kml or "31.2" in kml  # coordinates present

    def test_flight_log_to_csv(self):
        points = [
            FlightPoint(lat=31.23, lon=121.47, alt=50.0, speed=10.0, time_s=0.0, heading=90.0),
        ]
        log = FlightLog(points=points)
        csv_out = log.to_csv()
        assert "time_s" in csv_out
        assert "31.2300" in csv_out or "31.2" in csv_out

    def test_parse_csv_basic(self, tmp_path):
        csv_file = tmp_path / "flight.csv"
        csv_file.write_text(
            "lat,lon,alt,speed,time_s\n"
            "31.230,121.470,50.0,10.0,0.0\n"
            "31.231,121.471,55.0,10.0,10.0\n"
            "31.232,121.472,60.0,10.0,20.0\n",
            encoding="utf-8",
        )
        log = parse_csv(csv_file)
        assert len(log) == 3
        assert log.points[0].lat == pytest.approx(31.230)
        assert log.stats().max_altitude_m == 60.0

    def test_parse_csv_tab_delimited(self, tmp_path):
        csv_file = tmp_path / "flight.tsv"
        csv_file.write_text(
            "lat\tlon\talt\n"
            "31.230\t121.470\t50.0\n"
            "31.231\t121.471\t55.0\n",
            encoding="utf-8",
        )
        log = parse_csv(csv_file)
        assert len(log) == 2

    def test_parse_csv_skips_bad_rows(self, tmp_path):
        csv_file = tmp_path / "flight.csv"
        csv_file.write_text(
            "lat,lon,alt\n"
            "31.230,121.470,50.0\n"
            "INVALID,INVALID,INVALID\n"  # bad row
            "91.0,181.0,50.0\n"        # out of range
            "31.231,121.471,55.0\n",
            encoding="utf-8",
        )
        log = parse_csv(csv_file)
        # Only valid rows kept (2 valid, 2 invalid)
        assert len(log) == 2

    def test_parse_csv_missing_columns(self, tmp_path):
        csv_file = tmp_path / "flight.csv"
        csv_file.write_text(
            "lat,lon,alt,speed,heading\n"
            "31.230,121.470,50.0,10.0,90.0\n"
            "31.231,121.471,55.0,12.0,95.0\n",
            encoding="utf-8",
        )
        log = parse_csv(csv_file)
        assert len(log) == 2
        assert log.points[0].speed == pytest.approx(10.0)
        assert log.points[0].heading == pytest.approx(90.0)

    def test_parse_csv_not_found_raises(self):
        with pytest.raises(ValueError, match="not found"):
            parse_csv("/nonexistent/path/flight.csv")

    def test_parse_csv_no_coords_raises(self, tmp_path):
        csv_file = tmp_path / "flight.csv"
        csv_file.write_text("col1,col2\nval1,val2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="latitude and longitude"):
            parse_csv(csv_file)


class TestCompareToPlan:
    def test_compare_to_plan_full_coverage(self, tmp_path):
        # Create a flight log that exactly follows the plan
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps({
            "name": "Test", "waypoints": [
                {"lat": 31.230, "lon": 121.470, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 0},
                {"lat": 31.231, "lon": 121.471, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 1},
            ]
        }), encoding="utf-8")

        flight_points = [
            FlightPoint(lat=31.230, lon=121.470, alt=50.0, time_s=0.0),
            FlightPoint(lat=31.231, lon=121.471, alt=50.0, time_s=10.0),
        ]
        log = FlightLog(points=flight_points)
        mission = Mission.load(plan_file)

        result = compare_to_plan(log, mission)
        assert result["total_plan_waypoints"] == 2
        assert result["waypoint_hits_10m"] == 2  # both waypoints hit within 10m
        assert result["waypoint_hits_20m"] == 2
        assert result["waypoint_hits_50m"] == 2

    def test_compare_to_plan_partial_coverage(self, tmp_path):
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps({
            "name": "Test", "waypoints": [
                {"lat": 31.230, "lon": 121.470, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 0},
                {"lat": 31.231, "lon": 121.471, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 1},
                {"lat": 31.232, "lon": 121.472, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 2},
            ]
        }), encoding="utf-8")

        # Flight only covers the first waypoint
        flight_points = [
            FlightPoint(lat=31.230, lon=121.470, alt=50.0, time_s=0.0),
            FlightPoint(lat=31.2305, lon=121.471, alt=50.0, time_s=5.0),
        ]
        log = FlightLog(points=flight_points)
        mission = Mission.load(plan_file)

        result = compare_to_plan(log, mission)
        assert result["waypoint_hits_10m"] == 1
        assert result["waypoint_hits_20m"] == 1
        assert result["waypoint_hits_50m"] == 1  # third waypoint far away
        assert result["total_plan_waypoints"] == 3


class TestKmlImport:
    def test_parse_kml_basic(self, tmp_path):
        kml_file = tmp_path / "site.kml"
        kml_file.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
            '<Document><name>Test Site</name>\n'
            '<Placemark><name>WP1</name>\n'
            '<Point><coordinates>121.470,31.230,50</coordinates></Point>\n'
            '</Placemark>\n'
            '<Placemark><name>WP2</name>\n'
            '<Point><coordinates>121.471,31.231,55</coordinates></Point>\n'
            '</Placemark>\n'
            '</Document></kml>',
            encoding="utf-8",
        )
        doc = parse_kml(kml_file)
        assert doc.name == "Test Site"
        assert len(doc.waypoints) == 2
        assert doc.waypoints[0].lat == pytest.approx(31.230)
        assert doc.waypoints[0].lon == pytest.approx(121.470)
        assert doc.waypoints[0].alt == pytest.approx(50.0)
        assert doc.waypoints[0].name == "WP1"

    def test_kml_linestring(self, tmp_path):
        kml_file = tmp_path / "path.kml"
        kml_file.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
            '<Document><Placemark>\n'
            '<LineString><coordinates>121.470,31.230,50 121.471,31.231,55 121.472,31.232,60</coordinates></LineString>\n'
            '</Placemark></Document></kml>',
            encoding="utf-8",
        )
        doc = parse_kml(kml_file)
        assert len(doc.waypoints) == 3

    def test_kml_to_mission(self, tmp_path):
        kml_file = tmp_path / "site.kml"
        kml_file.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
            '<Document><Placemark><Point><coordinates>121.470,31.230,50</coordinates></Point></Placemark>\n'
            '<Placemark><Point><coordinates>121.471,31.231,60</coordinates></Point></Placemark>\n'
            '</Document></kml>',
            encoding="utf-8",
        )
        doc = parse_kml(kml_file)
        mission = doc.to_mission(default_alt=50.0, default_speed=10.0)
        assert len(mission) == 2
        assert mission[0].alt == 50.0
        assert mission[1].alt == 60.0

    def test_kml_not_found_raises(self):
        with pytest.raises(ValueError, match="not found"):
            parse_kml("/nonexistent.kml")


class TestTemplates:
    def test_get_templates_returns_list(self):
        templates = get_templates()
        assert len(templates) >= 5
        for t in templates:
            assert t.name
            assert t.category
            assert len(t.mission) > 0

    def test_template_to_dict_roundtrip(self):
        templates = get_templates()
        t = templates[0]
        d = t.to_dict()
        assert d["name"] == t.name
        assert d["category"] == t.category
        restored = MissionTemplate.from_dict(d)
        assert restored.name == t.name
        assert len(restored.mission) == len(t.mission)

    def test_template_categories(self):
        templates = get_templates()
        categories = {t.category for t in templates}
        assert "survey" in categories
        assert "inspection" in categories


class TestMavlinkLink:
    def test_connection_state_enum(self):
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.CONNECTED.value == "connected"

    def test_heartbeat_info_default(self):
        hb = HeartbeatInfo()
        assert hb.armed is False
        assert hb.autopilot_type == ""
        assert hb.system_status == ""

    def test_connection_info_default(self):
        from mavplan.mavlink_link import ConnectionInfo
        info = ConnectionInfo(device="/dev/ttyUSB0")
        assert info.device == "/dev/ttyUSB0"
        assert info.baudrate == 57600
        assert info.target_system == 1


class TestSimulate:
    def test_battery_model_capacity_wh(self):
        from mavplan.simulate import BatteryModel
        b = BatteryModel(capacity_mah=5000, voltage=22.2)
        assert b.capacity_wh == pytest.approx(111.0, abs=0.1)

    def test_wind_speed_factor_headwind(self):
        from mavplan.simulate import WindModel, WindDirection
        w = WindModel(speed_ms=5.0, direction=WindDirection.HEADWIND)
        f = w.speed_factor()
        assert f < 1.0

    def test_wind_speed_factor_tailwind(self):
        from mavplan.simulate import WindModel, WindDirection
        w = WindModel(speed_ms=5.0, direction=WindDirection.TAILWIND)
        f = w.speed_factor()
        assert f > 1.0

    def test_estimate_energy_simple(self, tmp_path):
        from mavplan.simulate import BatteryModel, SimulationParams, estimate_energy
        mission_file = tmp_path / "m.json"
        mission_file.write_text(json.dumps({
            "name": "Test", "waypoints": [
                {"lat": 31.230, "lon": 121.470, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 0},
                {"lat": 31.235, "lon": 121.475, "alt": 50.0, "speed": 10.0, "delay": 5, "yaw": -9999, "seq": 1},
            ]
        }), encoding="utf-8")
        mission = Mission.load(mission_file)
        params = SimulationParams(battery=BatteryModel(capacity_mah=5000, voltage=22.2))
        result = estimate_energy(mission, params)
        assert result.total_distance_m > 0
        assert result.total_time_s > 0
        assert result.energy_consumed_wh > 0
        assert 0 <= result.battery_used_percent <= 100

    def test_estimate_energy_insufficient_battery(self, tmp_path):
        from mavplan.simulate import BatteryModel, SimulationParams, estimate_energy
        mission_file = tmp_path / "m.json"
        # Large mission that exceeds battery
        wps = [{"lat": 31.230, "lon": 121.470, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 0}]
        lat, lon = 31.230, 121.470
        for i in range(50):
            lat += 0.01
            wps.append({"lat": lat, "lon": lon, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": i+1})
        mission_file.write_text(json.dumps({"name": "Long", "waypoints": wps}), encoding="utf-8")
        mission = Mission.load(mission_file)
        params = SimulationParams(battery=BatteryModel(capacity_mah=500, voltage=22.2))
        result = estimate_energy(mission, params)
        assert not result.feasible
        assert result.battery_used_percent > 100

    def test_insert_takeoff_landing(self, tmp_path):
        from mavplan.simulate import SimulationParams, insert_takeoff_landing
        mission_file = tmp_path / "m.json"
        mission_file.write_text(json.dumps({
            "name": "Test", "waypoints": [
                {"lat": 31.230, "lon": 121.470, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 0},
                {"lat": 31.235, "lon": 121.475, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 1},
            ]
        }), encoding="utf-8")
        mission = Mission.load(mission_file)
        params = SimulationParams()
        new_mission = insert_takeoff_landing(mission, params)
        # Original 2 + takeoff + landing = 4
        assert len(new_mission) == 4
        assert new_mission[0].alt == params.takeoff_altitude
        assert new_mission[-1].alt == 0.0

    def test_check_geofence_pass(self, tmp_path):
        from mavplan.simulate import check_geofence
        mission_file = tmp_path / "m.json"
        mission_file.write_text(json.dumps({
            "name": "Test", "waypoints": [
                {"lat": 31.230, "lon": 121.470, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 0},
                {"lat": 31.231, "lon": 121.471, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 1},
            ]
        }), encoding="utf-8")
        mission = Mission.load(mission_file)
        warnings = check_geofence(mission, max_range_m=5000.0)
        assert len(warnings) == 0

    def test_check_geofence_violation(self, tmp_path):
        from mavplan.simulate import check_geofence
        mission_file = tmp_path / "m.json"
        mission_file.write_text(json.dumps({
            "name": "Test", "waypoints": [
                {"lat": 31.230, "lon": 121.470, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 0},
                {"lat": 31.280, "lon": 121.520, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 1},
            ]
        }), encoding="utf-8")
        mission = Mission.load(mission_file)
        warnings = check_geofence(mission, max_range_m=500.0)
        assert len(warnings) >= 1

    def test_generate_report(self, tmp_path):
        from mavplan.simulate import BatteryModel, SimulationParams, generate_report
        mission_file = tmp_path / "m.json"
        mission_file.write_text(json.dumps({
            "name": "Test", "waypoints": [
                {"lat": 31.230, "lon": 121.470, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 0},
                {"lat": 31.235, "lon": 121.475, "alt": 50.0, "speed": 10.0, "delay": 0, "yaw": -9999, "seq": 1},
            ]
        }), encoding="utf-8")
        mission = Mission.load(mission_file)
        params = SimulationParams(battery=BatteryModel(capacity_mah=5000, voltage=22.2))
        report = generate_report(mission, params)
        assert "Mission Simulation Report" in report
        assert "Total distance" in report
        assert "Battery" in report


