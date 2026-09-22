"""Tests for the offline flight replay page (v1.13 ``analyze replay``)."""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from mavplan import cli
from mavplan.flightlog import FlightLog, FlightPoint
from mavplan.mission import Mission
from mavplan.replay_html import render_replay_html

ROOT = Path(__file__).resolve().parents[1]
FLIGHT_CSV = ROOT / "examples" / "v13_flight_li_ming.csv"


def _plan() -> Mission:
    m = Mission(name="replay-demo", home=(31.230, 121.470, 0.0))
    m.add_waypoint(lat=31.230, lon=121.470, alt=50)
    m.add_waypoint(lat=31.232, lon=121.470, alt=60)
    m.add_waypoint(lat=31.232, lon=121.475, alt=55)
    m.add_waypoint(lat=31.230, lon=121.475, alt=45)
    return m


def _flight(n: int = 240) -> FlightLog:
    pts = []
    for i in range(n):
        f = i / (n - 1)
        pts.append(
            FlightPoint(
                lat=31.230 + 0.002 * f,
                lon=121.470 + 0.005 * math.sin(f * math.pi),
                alt=20.0 + 60.0 * f,
                speed=8.0 + 4.0 * math.sin(f * 6.0),
                time_s=f * 300.0,
                heading=(f * 360.0) % 360.0,
            )
        )
    return FlightLog(points=pts, source_file="synthetic.csv")


def _frame_count(doc: str) -> int:
    m = re.search(r"var TRK = (\[.*?\]);", doc, re.DOTALL)
    assert m, "embedded TRK array not found"
    return len(re.findall(r"\[[-\d.,]+\]", m.group(1)))


class TestRenderReplayHtml:
    def test_renders_self_contained_document(self) -> None:
        doc = render_replay_html(_flight(), _plan())
        assert doc.lstrip().startswith("<!DOCTYPE html>")
        assert 'id="map"' in doc
        assert 'id="profile"' in doc
        assert 'id="marker"' in doc
        assert 'id="pcursor"' in doc
        assert "飞行回放" in doc

    def test_no_external_resources(self) -> None:
        doc = render_replay_html(_flight())
        assert "http://" not in doc
        assert "https://" not in doc
        assert "<script src" not in doc
        assert "<link " not in doc

    def test_placeholders_are_substituted(self) -> None:
        doc = render_replay_html(_flight(), _plan(), fps=12)
        for token in ("__TRK__", "__FPS__", "__PW__", "__PPAD__", "__DMAX__",
                      "__MAXALT__", "__MAXSPD__"):
            assert token not in doc
        assert "var FPS = 12;" in doc

    def test_timeline_and_gauges_present(self) -> None:
        doc = render_replay_html(_flight(), max_frames=100)
        assert 'id="tl" type="range"' in doc
        assert 'max="99"' in doc
        assert 'id="play"' in doc
        assert 'id="reset"' in doc
        assert 'id="rate"' in doc
        assert 'id="g-alt"' in doc
        assert 'id="g-spd"' in doc
        assert 'id="g-hdg"' in doc
        assert 'id="g-t"' in doc

    def test_frames_are_downsampled(self) -> None:
        doc = render_replay_html(_flight(n=1200), max_frames=120)
        assert _frame_count(doc) <= 120
        assert _frame_count(doc) >= 2

    def test_short_log_is_not_padded(self) -> None:
        doc = render_replay_html(_flight(n=30))
        assert _frame_count(doc) == 30

    def test_plan_overlay_and_comparison(self) -> None:
        doc = render_replay_html(_flight(), _plan())
        assert 'class="plan-line"' in doc
        assert 'class="trk-line"' in doc
        assert "plan-line" in doc and "计划对比" in doc
        assert "航线覆盖率" in doc
        assert "replay-demo" in doc

    def test_without_plan_has_no_plan_layer(self) -> None:
        doc = render_replay_html(_flight())
        assert "计划对比" not in doc
        assert "未提供计划" in doc
        assert "green" not in doc.lower()

    def test_writes_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "nested" / "replay.html"
            doc = render_replay_html(_flight(), output_path=str(out))
            assert out.is_file()
            assert out.read_text(encoding="utf-8") == doc

    def test_rejects_invalid_fps(self) -> None:
        for bad in (0, -3, 61):
            with pytest.raises(ValueError):
                render_replay_html(_flight(), fps=bad)

    def test_rejects_empty_log(self) -> None:
        with pytest.raises(ValueError):
            render_replay_html(FlightLog(points=[], source_file="empty.csv"))

    def test_real_log_stays_below_two_megabytes(self) -> None:
        if not FLIGHT_CSV.is_file():  # pragma: no cover - asset guard
            pytest.skip("example flight log missing")
        from mavplan.flightlog import parse_csv

        doc = render_replay_html(parse_csv(FLIGHT_CSV))
        assert len(doc.encode("utf-8")) < 2 * 1024 * 1024


class TestReplayCli:
    @pytest.fixture()
    def runner(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "MISSION_FILE", tmp_path / "mission.json")
        return CliRunner()

    def test_replay_writes_html(self, runner, tmp_path) -> None:
        if not FLIGHT_CSV.is_file():  # pragma: no cover - asset guard
            pytest.skip("example flight log missing")
        out = tmp_path / "replay.html"
        res = runner.invoke(
            cli.main,
            ["analyze", "replay", str(FLIGHT_CSV), "-o", str(out), "--fps", "20"],
        )
        assert res.exit_code == 0, res.output
        assert "Replay written" in res.output
        assert "20 fps" in res.output
        assert out.is_file()
        assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")

    def test_replay_with_plan(self, runner, tmp_path) -> None:
        if not FLIGHT_CSV.is_file():  # pragma: no cover - asset guard
            pytest.skip("example flight log missing")
        plan_file = tmp_path / "plan.json"
        _plan().save(str(plan_file))
        out = tmp_path / "replay_plan.html"
        res = runner.invoke(
            cli.main,
            ["analyze", "replay", str(FLIGHT_CSV), "--plan", str(plan_file), "-o", str(out)],
        )
        assert res.exit_code == 0, res.output
        assert "Plan: replay-demo" in res.output
        assert 'class="plan-line"' in out.read_text(encoding="utf-8")

    def test_replay_rejects_bad_fps(self, runner, tmp_path) -> None:
        if not FLIGHT_CSV.is_file():  # pragma: no cover - asset guard
            pytest.skip("example flight log missing")
        res = runner.invoke(
            cli.main,
            ["analyze", "replay", str(FLIGHT_CSV), "-o", str(tmp_path / "x.html"), "--fps", "0"],
        )
        assert res.exit_code != 0
        assert "fps" in res.output.lower()

    def test_replay_help_is_registered(self, runner) -> None:
        res = runner.invoke(cli.main, ["analyze", "--help"])
        assert res.exit_code == 0
        assert "replay" in res.output
