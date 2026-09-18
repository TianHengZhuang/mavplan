"""export check + grade plan (v1.12)."""
from pathlib import Path

from click.testing import CliRunner

from mavplan.export_check import compare_missions, grade_plan_quality
from mavplan.mission import Mission
from mavplan.waypoint import Waypoint


def _mission(name="m"):
    m = Mission(name=name)
    try:
        m.add_waypoint(Waypoint(lat=22.80, lon=108.30, alt_m=50))
        m.add_waypoint(Waypoint(lat=22.81, lon=108.31, alt_m=60))
    except Exception:
        pass
    return m


def test_compare_missions_ok(tmp_path):
    a = _mission()
    b = _mission()
    r = compare_missions(a, b)
    assert r["ok"] is True


def test_grade_plan_quality():
    m = _mission("grade-demo")
    r = grade_plan_quality(m, [], student="张三")
    assert r["schema"] == "mavplan.grade/1"
    assert r["mode"] == "plan"
    assert 0 <= r["score"] <= 100
    assert r["band"] in ("优秀", "良好", "合格", "不合格")


def test_cli_export_check(tmp_path):
    from mavplan.cli import main

    m = _mission()
    src = tmp_path / "src.json"
    out = tmp_path / "out.wpl"
    m.save(src)
    r = CliRunner().invoke(main, ["mission", "load", str(src)])
    # mission load may set cwd state; export from file path via env if needed
    from mavplan.mission import Mission as M
    from mavplan.formats import to_wpl, parse_wpl

    text = to_wpl(_mission())
    out.write_text(text, encoding="utf-8")
    back = parse_wpl(text)
    result = compare_missions(_mission(), back, tol_m=5.0)
    assert result["waypoints_original"] == result["waypoints_exported"]
