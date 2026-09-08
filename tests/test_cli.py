"""CLI end-to-end tests for mavplan (v1.0).

Run every public command through click's CliRunner with an isolated
mission file, so the real ~/.mavplan is never touched.
"""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from mavplan import cli


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    """CliRunner with MISSION_FILE redirected into the test tmp dir."""
    monkeypatch.setattr(cli, "MISSION_FILE", tmp_path / "mission.json")
    return CliRunner()


def _invoke(runner, args):
    result = runner.invoke(cli.main, args)
    assert result.exit_code == 0, f"exit={result.exit_code} output={result.output!r}"
    return result


# ----------------------------------------------------------------------
# waypoint
# ----------------------------------------------------------------------


def test_waypoint_add_list_clear(runner):
    _invoke(runner, ["waypoint", "add", "--lat", "31.23", "--lon", "121.47", "--alt", "50"])
    _invoke(runner, ["waypoint", "add", "--lat", "31.24", "--lon", "121.48", "--alt", "60"])
    res = _invoke(runner, ["waypoint", "list"])
    assert "31.23" in res.output and "31.24" in res.output
    res = _invoke(runner, ["waypoint", "clear"])
    assert "Mission cleared" in res.output
    res = _invoke(runner, ["waypoint", "list"])
    assert "31.23" not in res.output


def test_waypoint_add_invalid_lat_rejected(runner):
    res = runner.invoke(cli.main, ["waypoint", "add", "--lat", "95", "--lon", "121", "--alt", "50"])
    assert res.exit_code != 0
    assert "out of range" in res.output.lower() or "invalid" in res.output.lower()


# ----------------------------------------------------------------------
# generate / mission
# ----------------------------------------------------------------------


def test_generate_lawnmower_and_validate(runner):
    res = _invoke(
        runner,
        ["generate", "lawnmower", "--corner1", "31.230,121.470", "--corner2", "31.240,121.480",
         "--alt", "50", "--spacing", "20"],
    )
    assert "waypoints" in res.output.lower()
    res = _invoke(runner, ["mission", "validate"])
    assert "OK" in res.output


def test_generate_orbit_saves(runner):
    res = _invoke(
        runner,
        ["generate", "orbit", "--center", "31.235,121.475", "--radius", "50",
         "--alt", "50", "--points", "8"],
    )
    assert "Orbit" in res.output


def test_generate_polygon_saves(runner):
    res = _invoke(
        runner,
        ["generate", "polygon", "--polygon", "31.23,121.47", "--polygon", "31.24,121.47",
         "--polygon", "31.24,121.48", "--polygon", "31.23,121.48", "--alt", "50"],
    )
    assert "Polygon" in res.output or "polygon" in res.output.lower()


def test_mission_save_and_load(runner, tmp_path):
    _invoke(runner, ["waypoint", "add", "--lat", "31.23", "--lon", "121.47", "--alt", "50"])
    saved = tmp_path / "m1.json"
    _invoke(runner, ["mission", "save", str(saved)])
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert len(data["waypoints"]) == 1
    _invoke(runner, ["mission", "load", str(saved)])
    res = _invoke(runner, ["waypoint", "list"])
    assert "31.23" in res.output


# ----------------------------------------------------------------------
# export
# ----------------------------------------------------------------------


def test_export_kml_and_mavlink_and_csv(runner, tmp_path):
    _invoke(runner, ["waypoint", "add", "--lat", "31.23", "--lon", "121.47", "--alt", "50"])
    for fmt, ext in (("kml", "kml"), ("mavlink", "txt"), ("csv", "csv")):
        out = tmp_path / f"mission.{ext}"
        _invoke(runner, ["export", fmt, "-o", str(out)])
        assert out.exists() and out.stat().st_size > 0


# ----------------------------------------------------------------------
# analyze
# ----------------------------------------------------------------------


def test_analyze_log(tmp_path, runner):
    csv_path = tmp_path / "flight.csv"
    csv_path.write_text(
        "lat,lon,alt\n"
        "31.230,121.470,50.0\n"
        "31.231,121.471,50.5\n"
        "31.232,121.472,51.0\n",
        encoding="utf-8",
    )
    res = _invoke(runner, ["analyze", "log", str(csv_path)])
    assert "distance" in res.output.lower()


def test_analyze_compare(tmp_path, runner):
    csv_path = tmp_path / "flight.csv"
    csv_path.write_text(
        "lat,lon,alt\n"
        "31.230,121.470,50.0\n"
        "31.231,121.471,50.5\n"
        "31.232,121.472,51.0\n",
        encoding="utf-8",
    )
    _invoke(runner, ["waypoint", "add", "--lat", "31.230", "--lon", "121.470", "--alt", "50"])
    plan = tmp_path / "plan.json"
    _invoke(runner, ["mission", "save", str(plan)])
    out = tmp_path / "cmp.kml"
    res = _invoke(runner, ["analyze", "compare", str(csv_path), str(plan), "-o", str(out)])
    assert "Within 10m" in res.output
    assert out.exists() and out.stat().st_size > 0


# ----------------------------------------------------------------------
# template
# ----------------------------------------------------------------------


def test_template_list_and_load(runner, tmp_path):
    res = _invoke(runner, ["template", "list"])
    assert "survey" in res.output.lower()
    out = tmp_path / "tpl.kml"
    res = _invoke(runner, ["template", "load", "survey", "--output", str(out)])
    assert out.exists() and out.stat().st_size > 0


# ----------------------------------------------------------------------
# simulate
# ----------------------------------------------------------------------


@pytest.fixture()
def saved_mission(runner, tmp_path):
    _invoke(
        runner,
        ["generate", "orbit", "--center", "31.235,121.475", "--radius", "30",
         "--alt", "50", "--points", "6"],
    )
    path = tmp_path / "orbit.json"
    _invoke(runner, ["mission", "save", str(path)])
    return path


def test_simulate_run(saved_mission, runner):
    res = _invoke(runner, ["simulate", "run", str(saved_mission), "--capacity", "8000"])
    assert "energy" in res.output.lower() or "battery" in res.output.lower()


def test_simulate_battery(saved_mission, runner):
    res = _invoke(runner, ["simulate", "battery", str(saved_mission), "--capacity", "8000"])
    assert "%" in res.output or "remaining" in res.output.lower()


def test_simulate_geofence_within_range(saved_mission, runner):
    res = _invoke(runner, ["simulate", "geofence", str(saved_mission), "--max-range", "5000"])
    assert "OK" in res.output or "within" in res.output.lower()


def test_simulate_with_tol(saved_mission, runner, tmp_path):
    out = tmp_path / "tol.json"
    _invoke(runner, ["simulate", "with-tol", str(saved_mission), "--output", str(out)])
    assert out.exists()
