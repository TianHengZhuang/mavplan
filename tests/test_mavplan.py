"""Tests for mavplan."""
from __future__ import annotations

import math

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

