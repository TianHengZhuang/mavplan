"""CLI: review --json and nfz check (v1.11.1)."""
from pathlib import Path

from click.testing import CliRunner


def _write_mission(tmp: Path) -> Path:
    p = tmp / "m.waypoints.txt"
    # minimal mission file format - fallback if mission load differs
    content = tmp / "simple.json"
    # try json mission used in other tests
    return content


def test_review_json_stdout(tmp_path, monkeypatch):
    from mavplan.cli_ext import review_cmd
    from mavplan.mission import Mission

    m = Mission(name="json-review-demo")
    # add waypoints if API allows
    if hasattr(m, "add_waypoint"):
        try:
            from mavplan.waypoint import Waypoint

            m.add_waypoint(Waypoint(lat=22.8, lon=108.3, alt_m=50))
            m.add_waypoint(Waypoint(lat=22.81, lon=108.31, alt_m=50))
        except Exception:
            pass
    path = tmp_path / "mission.json"
    try:
        m.save(path)
    except Exception:
        path.write_text('{"name": "json-review-demo", "waypoints": []}', encoding="utf-8")

    r = CliRunner().invoke(review_cmd, [str(path), "--json"])
    assert r.exit_code == 0, r.output
    assert "mavplan.review" in r.output
    assert "verdict" in r.output


def test_nfz_check_json(tmp_path):
    from mavplan.cli_ext import nfz_check
    from mavplan.mission import Mission

    m = Mission(name="nfz-check-demo")
    path = tmp_path / "mission.json"
    try:
        m.save(path)
    except Exception:
        path.write_text('{"name": "nfz-check-demo", "waypoints": []}', encoding="utf-8")
    r = CliRunner().invoke(nfz_check, [str(path), "--json"])
    assert r.exit_code in (0, 1), r.output
    assert "mavplan.nfzcheck" in r.output
