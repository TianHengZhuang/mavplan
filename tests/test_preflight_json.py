"""Tests for structured preflight report (mavplan.preflight/1)."""
import json

from mavplan import Mission, PreflightParams, preflight_report, preflight_summary


def _mission(alt: float = 50.0) -> Mission:
    m = Mission(name="preflight-json")
    m.add_waypoint(lat=31.230, lon=121.470, alt=10)
    m.add_waypoint(lat=31.235, lon=121.475, alt=alt)
    m.add_waypoint(lat=31.240, lon=121.480, alt=50)
    return m


def test_report_schema_and_summary():
    report = preflight_report(_mission())
    assert report["schema"] == "mavplan.preflight/1"
    assert report["mission"]["waypoints"] == 3
    assert report["zones"] == 0
    assert set(report["summary"]) == {"errors", "warnings", "info"}
    assert isinstance(report["checks"], list)


def test_report_flags_max_altitude_error():
    report = preflight_report(
        _mission(alt=500.0),
        params=PreflightParams(max_altitude_m=120.0),
    )
    codes = [c["code"] for c in report["checks"]]
    assert "max_altitude" in codes
    assert report["summary"]["errors"] >= 1


def test_empty_mission_report():
    report = preflight_report(Mission(name="empty"))
    assert report["checks"][0]["code"] == "empty_mission"
    assert report["summary"]["errors"] == 1


def test_report_json_serializable():
    payload = json.dumps(preflight_report(_mission()), ensure_ascii=False)
    assert '"schema": "mavplan.preflight/1"' in payload


def test_summary_matches_report():
    m = _mission(alt=500.0)
    params = PreflightParams(max_altitude_m=120.0)
    report = preflight_report(m, params=params)
    assert report["summary"] == preflight_summary(report["checks"])


def test_single_waypoint_reports_info():
    m = Mission(name="one")
    m.add_waypoint(lat=31.23, lon=121.47, alt=50)
    report = preflight_report(m)
    assert report["summary"]["errors"] == 0
    assert report["checks"][0]["code"] == "single_waypoint"
    assert report["checks"][0]["level"] == "info"
    assert report["summary"]["info"] == 1


def test_cli_check_output_file(tmp_path):
    from click.testing import CliRunner

    from mavplan.cli import main

    plan = tmp_path / "plan.json"
    _mission().save(plan)
    out = tmp_path / "preflight.json"
    res = CliRunner().invoke(
        main,
        ["mission", "check", str(plan), "-o", str(out), "--max-distance", "5000"],
    )
    assert res.exit_code == 0, res.output
    assert out.exists()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "mavplan.preflight/1"
    assert doc["mission"]["waypoints"] == 3
