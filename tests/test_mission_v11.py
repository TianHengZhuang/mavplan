"""Tests for Mission v1.1 API: home, insert, actions, camera triggers."""
import pytest

from mavplan import Mission
from mavplan.actions import (
    DO_CHANGE_SPEED,
    DO_GRIPPER,
    DO_SET_CAM_TRIGG_DIST,
    DO_SET_CAM_TRIGG_INTERVAL,
)


def make_mission() -> Mission:
    m = Mission(name="Test", home=(31.2, 121.4, 10.0))
    m.add_waypoint(lat=31.23, lon=121.47, alt=50, speed=10)
    m.add_waypoint(lat=31.24, lon=121.49, alt=60)
    m.add_waypoint(lat=31.25, lon=121.51, alt=70)
    return m


class TestHome:
    def test_default_none(self):
        assert Mission().home is None

    def test_set_home(self):
        m = Mission(home=(1.0, 2.0, 3.0))
        assert m.home == (1.0, 2.0, 3.0)

    def test_home_persists_via_dict(self):
        m = make_mission()
        d = m.to_dict()
        assert d["home"] == [31.2, 121.4, 10.0]
        m2 = Mission.from_dict(d)
        assert m2.home == (31.2, 121.4, 10.0)
        assert len(m2) == 3

    def test_home_absent_in_old_dicts(self):
        m = Mission.from_dict({"name": "x", "waypoints": []})
        assert m.home is None


class TestInsertWaypoint:
    def test_insert_middle_renumbers(self):
        m = make_mission()
        wp = m.insert_waypoint(1, lat=31.235, lon=121.48, alt=55)
        assert [w.seq for w in m.waypoints()] == [0, 1, 2, 3]
        assert m.waypoints()[1] is wp
        assert m.waypoints()[2].lat == pytest.approx(31.24)

    def test_insert_front(self):
        m = make_mission()
        m.insert_waypoint(0, lat=31.1, lon=121.1, alt=10)
        assert m.waypoints()[0].lat == pytest.approx(31.1)
        assert m.waypoints()[1].seq == 1

    def test_insert_end(self):
        m = make_mission()
        m.insert_waypoint(len(m), lat=31.9, lon=121.9, alt=90)
        assert len(m) == 4
        assert m.waypoints()[-1].seq == 3


class TestRemoveWaypoint:
    def test_remove_renumbers(self):
        m = make_mission()
        m.remove_waypoint(1)
        assert len(m) == 2
        assert [w.seq for w in m.waypoints()] == [0, 1]
        assert m.waypoints()[1].lat == pytest.approx(31.25)

    def test_remove_missing_raises(self):
        m = make_mission()
        with pytest.raises(IndexError):
            m.remove_waypoint(99)


class TestAddAction:
    def test_inserts_after_seq(self):
        m = make_mission()
        act = m.add_action(0, "DO_CHANGE_SPEED", param1=5.0)
        wps = m.waypoints()
        assert len(wps) == 4
        assert wps[1] is act
        assert act.command == DO_CHANGE_SPEED
        assert act.delay == pytest.approx(5.0)  # param1 stored in delay
        assert [w.seq for w in wps] == [0, 1, 2, 3]

    def test_inherits_position(self):
        m = make_mission()
        act = m.add_action(0, "DO_GRIPPER", param1=1)
        assert act.lat == pytest.approx(m.waypoints()[0].lat)
        assert act.lon == pytest.approx(m.waypoints()[0].lon)
        assert act.alt == pytest.approx(m.waypoints()[0].alt)

    def test_explicit_position(self):
        m = make_mission()
        act = m.add_action(1, "DO_GRIPPER", lat=31.0, lon=121.0, alt=5.0)
        assert act.lat == pytest.approx(31.0)

    def test_numeric_command(self):
        m = make_mission()
        act = m.add_action(0, DO_GRIPPER, param1=1)
        assert act.command == DO_GRIPPER

    def test_unknown_command_raises(self):
        m = make_mission()
        with pytest.raises(ValueError):
            m.add_action(0, "BOGUS")


class TestCameraTrigger:
    def test_distance_mode(self):
        m = make_mission()
        act = m.add_camera_trigger("distance", 25.0, after_seq=0)
        assert act.command == DO_SET_CAM_TRIGG_DIST
        assert act.delay == pytest.approx(25.0)  # trigger every 25 m
        assert m.waypoints()[1] is act

    def test_time_mode(self):
        m = make_mission()
        act = m.add_camera_trigger("time", 2.0, after_seq=0)
        assert act.command == DO_SET_CAM_TRIGG_INTERVAL
        assert act.delay == pytest.approx(2.0)

    def test_bad_mode(self):
        m = make_mission()
        with pytest.raises(ValueError):
            m.add_camera_trigger("warp", 1.0)
