"""Tests for MAV_CMD action constants and helpers."""
import pytest

from mavplan.actions import (
    CMD_NAMES,
    NAV_WAYPOINT,
    NAV_TAKEOFF,
    DO_JUMP,
    DO_CHANGE_SPEED,
    DO_SET_CAM_TRIGG_DIST,
    DO_SET_CAM_TRIGG_INTERVAL,
    DO_GRIPPER,
    command_id,
    command_name,
    is_action,
)


class TestCommandId:
    def test_int_passthrough(self):
        assert command_id(16) == 16
        assert command_id(206) == 206

    def test_canonical_name(self):
        assert command_id("NAV_WAYPOINT") == 16
        assert command_id("DO_JUMP") == 177
        assert command_id("do_jump") == 177  # case-insensitive

    def test_full_prefix(self):
        assert command_id("MAV_CMD_NAV_WAYPOINT") == 16
        assert command_id("MAV_CMD_DO_SET_CAM_TRIGG_DIST") == 206

    def test_aliases(self):
        assert command_id("takeoff") == NAV_TAKEOFF
        assert command_id("change_speed") == DO_CHANGE_SPEED
        assert command_id("trigger_dist") == DO_SET_CAM_TRIGG_DIST
        assert command_id("trigger_interval") == DO_SET_CAM_TRIGG_INTERVAL
        assert command_id("rtl") == 20

    def test_unknown(self):
        assert command_id("BOGUS_COMMAND") is None


class TestCommandName:
    def test_known(self):
        assert command_name(16) == "NAV_WAYPOINT"
        assert command_name(177) == "DO_JUMP"
        assert command_name(206) == "DO_SET_CAM_TRIGG_DIST"

    def test_unknown(self):
        assert command_name(9999) == "UNKNOWN(9999)"

    def test_roundtrip(self):
        for cmd in CMD_NAMES:
            assert command_id(command_name(cmd)) == cmd


class TestIsAction:
    def test_nav_not_action(self):
        assert not is_action(NAV_WAYPOINT)
        assert not is_action(NAV_TAKEOFF)

    def test_do_is_action(self):
        assert is_action(DO_JUMP)
        assert is_action(DO_CHANGE_SPEED)
        assert is_action(DO_GRIPPER)
