"""Tests for grade_batch module (v1.6)."""
from __future__ import annotations

import csv
import json
import pytest
import tempfile
from pathlib import Path

from mavplan.grade_batch import (
    batch_grade,
    class_summary_text,
    load_roster,
    find_log_for_student,
    write_summary_csv,
    DEFAULT_PASS_SCORE,
    ClassResult,
    StudentRow,
)
from mavplan.scenario import load_scenario, default_scenarios_dir

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


class TestLoadRoster:
    def test_loads_valid_roster(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        ) as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["student_id", "name", "class"])
            w.writerow(["S001", "张三", "A班"])
            w.writerow(["S002", "李四", "B班"])
            p = Path(f.name)
        try:
            rows = load_roster(p)
            assert len(rows) == 2
            assert rows[0].student_id == "S001"
            assert rows[0].name == "张三"
            assert rows[0].extras["class"] == "A班"
        finally:
            p.unlink()

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_roster(Path("/nonexistent/roster.csv"))

    def test_missing_columns_raise(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        ) as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["student_id"])  # missing "name"
            w.writerow(["S001"])
            p = Path(f.name)
        try:
            with pytest.raises(ValueError, match="missing required columns"):
                load_roster(p)
        finally:
            p.unlink()


class TestFindLogForStudent:
    def test_finds_by_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            logs_dir = Path(d)
            (logs_dir / "S001_zhangsan.csv").write_text("dummy", encoding="utf-8")
            result = find_log_for_student("S001", logs_dir)
            assert result is not None
            assert result.name == "S001_zhangsan.csv"

    def test_finds_by_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            logs_dir = Path(d)
            (logs_dir / "001.csv").write_text("dummy", encoding="utf-8")
            result = find_log_for_student("001", logs_dir)
            assert result is not None

    def test_not_found_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            logs_dir = Path(d)
            result = find_log_for_student("S999", logs_dir)
            assert result is None

    def test_missing_dir_returns_none(self) -> None:
        result = find_log_for_student("S001", Path("/nonexistent"))
        assert result is None


class TestBatchGrade:
    def _make_minimal_roster(self, tmp: Path) -> Path:
        p = tmp / "roster.csv"
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["student_id", "name"])
            w.writerow(["S001", "张三"])
            w.writerow(["S002", "李四"])
        return p

    def _make_flight_log(self, logs_dir: Path, name: str) -> Path:
        p = logs_dir / f"{name}.csv"
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["lat", "lon", "alt", "time_s", "speed", "heading"])
            for i in range(10):
                w.writerow([f"31.19{i:04d}", "121.39", "50.0", f"{i}.0", "10.0", "90.0"])
        return p

    def _get_task_path(self, tmp: Path) -> Path:
        spec = load_scenario("rectangle_patrol", scenarios_dir=SCENARIOS_DIR)
        p = tmp / "task.json"
        spec.task.save(str(p))
        return p

    def test_batch_grade_all_found(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            logs_dir = tmp / "logs"
            logs_dir.mkdir()
            roster = self._make_minimal_roster(tmp)
            self._make_flight_log(logs_dir, "S001")
            self._make_flight_log(logs_dir, "S002")
            task = self._get_task_path(tmp)
            out = tmp / "reports"
            result = batch_grade(roster, logs_dir, task, out)
            assert len(result.students) == 2
            counts = result.summary_counts()
            assert counts["graded"] == 2
            assert (out / "class_summary.csv").is_file()
            assert (out / "S001.html").is_file()
            assert (out / "S002.html").is_file()

    def test_batch_grade_partial_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            logs_dir = tmp / "logs"
            logs_dir.mkdir()
            roster = self._make_minimal_roster(tmp)
            self._make_flight_log(logs_dir, "S001")
            # S002 has no log
            task = self._get_task_path(tmp)
            out = tmp / "reports"
            result = batch_grade(roster, logs_dir, task, out)
            statuses = {s.student_id: s.status for s in result.students}
            assert "ok" in statuses["S001"]
            assert "skipped" in statuses["S002"]

    def test_pass_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            logs_dir = tmp / "logs"
            logs_dir.mkdir()
            roster = self._make_minimal_roster(tmp)
            self._make_flight_log(logs_dir, "S001")
            self._make_flight_log(logs_dir, "S002")
            task = self._get_task_path(tmp)
            out = tmp / "reports"
            # Pass threshold 100 — nobody passes
            result = batch_grade(roster, logs_dir, task, out, pass_threshold=100.0)
            assert result.summary_counts()["passed"] == 0
            # Pass threshold 0 — everyone passes
            result2 = batch_grade(roster, logs_dir, task, out, pass_threshold=0.0)
            assert result2.summary_counts()["passed"] == 2


class TestClassSummaryText:
    def test_no_summary_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            text = class_summary_text(tmp)
            assert "未找到" in text


class TestClassResult:
    def test_summary_counts(self) -> None:
        r = ClassResult(task_name="test", pass_threshold=60.0)
        r.students.append(
            StudentRow(student_id="S001", name="A", status="ok", score=70.0, passed=True)
        )
        r.students.append(
            StudentRow(student_id="S002", name="B", status="ok", score=50.0, passed=False)
        )
        r.students.append(
            StudentRow(student_id="S003", name="C", status="skipped: no log", score=None, passed=None)
        )
        counts = r.summary_counts()
        assert counts["total"] == 3
        assert counts["graded"] == 2
        assert counts["passed"] == 1
        assert counts["failed"] == 1
        assert counts["skipped_or_error"] == 1

    def test_pass_rate(self) -> None:
        r = ClassResult(task_name="test", pass_threshold=60.0)
        r.students.append(
            StudentRow(student_id="S001", name="A", status="ok", score=70.0, passed=True)
        )
        r.students.append(
            StudentRow(student_id="S002", name="B", status="ok", score=50.0, passed=False)
        )
        assert r.pass_rate() == 0.5

    def test_pass_rate_zero_graded(self) -> None:
        r = ClassResult(task_name="test", pass_threshold=60.0)
        assert r.pass_rate() == 0.0
