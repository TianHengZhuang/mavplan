"""CLI end-to-end tests for mavplan v1.1 interop features."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from mavplan import cli

WPL_TEXT = """QGC WPL 110
0\t1\t0\t16\t0\t0\t0\t0\t31.2300000\t121.4700000\t10.00
1\t0\t3\t16\t0\t2\t0\t-9999\t31.2300000\t121.4800000\t50.00
2\t0\t3\t16\t0\t2\t0\t-9999\t31.2400000\t121.4900000\t60.00
"""


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "MISSION_FILE", tmp_path / "mission.json")
    return CliRunner()


def _invoke(runner, args):
    result = runner.invoke(cli.main, args)
    assert result.exit_code == 0, f"exit={result.exit_code} output={result.output!r}"
    return result


# ----------------------------------------------------------------------
# mission import (auto-detect: wpl / .plan / mavplan json)
# ----------------------------------------------------------------------


def test_import_wpl(runner, tmp_path):
    p = tmp_path / "in.waypoints"
    p.write_text(WPL_TEXT, encoding="utf-8")
    res = _invoke(runner, ["mission", "import", str(p)])
    assert "2 waypoints" in res.output
    res = _invoke(runner, ["waypoint", "list"])
    assert "31.240" in res.output


def test_import_wpl_home(runner, tmp_path):
    p = tmp_path / "in.waypoints"
    p.write_text(WPL_TEXT, encoding="utf-8")
    _invoke(runner, ["mission", "import", str(p)])
    res = _invoke(runner, ["mission", "list"])
    # home survived into the saved mission
    res = _invoke(runner, ["waypoint", "list"])
    assert "Mission:" in res.output


def test_import_qgc_plan(runner, tmp_path):
    plan = {
        "fileType": "Plan",
        "version": 1,
        "groundStation": "QGroundControl",
        "mission": {
            "plannedHomePosition": [31.2, 121.4, 10.0],
            "items": [
                {"command": 16, "frame": 3, "autoContinue": True,
                 "params": [0, 2, 0, -9999, 31.230, 121.470, 50.0]},
                {"command": 16, "frame": 3, "autoContinue": True,
                 "params": [0, 2, 0, -9999, 31.240, 121.490, 60.0]},
            ],
        },
    }
    p = tmp_path / "in.plan"
    p.write_text(json.dumps(plan), encoding="utf-8")
    res = _invoke(runner, ["mission", "import", str(p)])
    assert "2 waypoints" in res.output
    assert "home=(" in res.output


def test_import_unrecognised(runner, tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("garbage", encoding="utf-8")
    res = runner.invoke(cli.main, ["mission", "import", str(p)])
    assert res.exit_code == 1
    assert "Error importing" in res.output


# ----------------------------------------------------------------------
# export plan / wpl
# ----------------------------------------------------------------------


def _seed_two_wps(runner):
    _invoke(runner, ["waypoint", "add", "--lat", "31.23", "--lon", "121.47", "--alt", "50"])
    _invoke(runner, ["waypoint", "add", "--lat", "31.24", "--lon", "121.48", "--alt", "60"])


def test_export_plan(runner, tmp_path):
    _seed_two_wps(runner)
    p = tmp_path / "out.plan"
    _invoke(runner, ["export", "plan", "-o", str(p)])
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["fileType"] == "Plan"
    assert len(data["mission"]["items"]) == 2
    assert data["mission"]["items"][0]["params"][4] == 31.23


def test_export_plan_roundtrip_import(runner, tmp_path):
    _seed_two_wps(runner)
    p = tmp_path / "out.plan"
    _invoke(runner, ["export", "plan", "-o", str(p)])
    _invoke(runner, ["mission", "import", str(p)])
    res = _invoke(runner, ["waypoint", "list"])
    assert "31.230" in res.output and "31.240" in res.output


def test_export_wpl(runner, tmp_path):
    _seed_two_wps(runner)
    p = tmp_path / "out.waypoints"
    _invoke(runner, ["export", "wpl", "-o", str(p)])
    text = p.read_text(encoding="utf-8")
    assert text.startswith("QGC WPL 110")
    assert "\t16\t" in text


def test_export_plan_empty_fails(runner):
    res = runner.invoke(cli.main, ["export", "plan"])
    assert res.exit_code == 1
    assert "empty" in res.output


# ----------------------------------------------------------------------
# waypoint action
# ----------------------------------------------------------------------


def test_action_insert(runner):
    _seed_two_wps(runner)
    res = _invoke(runner, ["waypoint", "action", "0", "--command", "DO_CHANGE_SPEED", "--param1", "5"])
    assert "DO_CHANGE_SPEED after WP0" in res.output
    res = _invoke(runner, ["waypoint", "list"])
    assert "[DO_CHANGE_SPEED]" in res.output
    # seq renumbered: trailing nav waypoint is now WP2, its coords intact
    assert "WP2: lat=31.240" in res.output


def test_action_bad_seq(runner):
    _seed_two_wps(runner)
    res = runner.invoke(cli.main, ["waypoint", "action", "9", "--command", "DO_JUMP"])
    assert res.exit_code == 1


def test_action_unknown_command(runner):
    _seed_two_wps(runner)
    res = runner.invoke(cli.main, ["waypoint", "action", "0", "--command", "BOGUS"])
    assert res.exit_code == 1
    assert "unknown MAV_CMD" in res.output


def test_action_exported_to_wpl(runner, tmp_path):
    _seed_two_wps(runner)
    _invoke(runner, ["waypoint", "action", "0", "--command", "do_gripper", "--param1", "1"])
    p = tmp_path / "act.waypoints"
    _invoke(runner, ["export", "wpl", "-o", str(p)])
    text = p.read_text(encoding="utf-8")
    assert "\t211\t" in text  # DO_GRIPPER


# ----------------------------------------------------------------------
# mission camera
# ----------------------------------------------------------------------


def test_camera_distance(runner):
    _seed_two_wps(runner)
    res = _invoke(runner, ["mission", "camera", "--mode", "distance", "--value", "25", "--after", "0"])
    assert "DO_SET_CAM_TRIGG_DIST every 25m after WP0" in res.output
    res = _invoke(runner, ["waypoint", "list"])
    assert "[DO_SET_CAM_TRIGG_DIST]" in res.output


def test_camera_time(runner):
    _seed_two_wps(runner)
    res = _invoke(runner, ["mission", "camera", "--mode", "time", "--value", "2"])
    assert "DO_SET_CAM_TRIGG_INTERVAL every 2s after WP0" in res.output


def test_camera_empty_mission(runner):
    res = runner.invoke(cli.main, ["mission", "camera", "--value", "25"])
    assert res.exit_code == 1
    assert "empty" in res.output


def test_camera_bad_seq(runner):
    _seed_two_wps(runner)
    res = runner.invoke(cli.main, ["mission", "camera", "--value", "25", "--after", "5"])
    assert res.exit_code == 1
