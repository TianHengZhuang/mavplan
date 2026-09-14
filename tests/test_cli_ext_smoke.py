"""CLI smoke tests for fleet / nfz / review commands."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run_cli(*args: str, cwd: Path | None = None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["MAVPLAN_SCENARIOS"] = str(ROOT / "scenarios")
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "mavplan.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd or ROOT),
        env=env,
    )


def test_cli_help_has_new_groups():
    r = run_cli("--help")
    assert r.returncode == 0
    assert "fleet" in r.stdout
    assert "nfz" in r.stdout
    assert "review" in r.stdout


def test_cli_nfz_list_xuzhou():
    r = run_cli("nfz", "list", "江苏省", "徐州市")
    assert r.returncode == 0
    assert "徐州市" in r.stdout
    assert "云龙湖" in r.stdout or "机场" in r.stdout
    assert "zones:" in r.stdout


def test_cli_nfz_list_district():
    r = run_cli("nfz", "list", "江苏省", "徐州市", "--district", "云龙区")
    assert r.returncode == 0
    assert "云龙区" in r.stdout


def test_cli_nfz_unknown_province_fails():
    r = run_cli("nfz", "list", "火星省", "徐州市")
    assert r.returncode != 0


def test_cli_fleet_init_and_show(tmp_path: Path):
    out = tmp_path / "fleet.json"
    r = run_cli("fleet", "init", "--out", str(out), "--name", "测试任务")
    assert r.returncode == 0
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["count"] == 1
    r2 = run_cli("fleet", "show", str(out))
    assert r2.returncode == 0
    assert "测试任务" in r2.stdout


def test_cli_review_with_builtin_nfz(tmp_path: Path):
    # build a tiny mission json
    mission = {
        "name": "CLI 总结测试",
        "home": [34.2472, 117.1856, 0],
        "waypoints": [
            {"lat": 34.2472, "lon": 117.1856, "alt": 50, "speed": 8},
            {"lat": 34.250, "lon": 117.1856, "alt": 50, "speed": 8},
        ],
    }
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(mission), encoding="utf-8")
    r = run_cli(
        "review",
        str(mp),
        "--nfz-region",
        "江苏省",
        "徐州市",
        "-o",
        str(tmp_path / "review.md"),
    )
    assert r.returncode == 0
    text = (tmp_path / "review.md").read_text(encoding="utf-8")
    assert "任务前分析" in text
    assert "任务中分析" in text
    assert "任务后分析" in text
