"""Batch class grading (v1.6 training operations).

Given a roster CSV (one student per row) and a directory of student
flight logs (CSV/JSON), run ``grade.grade_flight`` for every student and
emit:

  - One HTML score report per student (named ``<student_id>.html``).
  - One CSV summary file (``class_summary.csv``) listing every student
    with their score, pass/fail status, and per-category deductions.

The roster CSV must have a header row with at minimum:
    student_id,name
and may optionally include any other columns (kept verbatim in the
summary CSV for the instructor's bookkeeping).

Flight log files are matched to a student by filename prefix or by the
``student_id`` value present in the log header, so a folder layout like
::

    logs/
        S001_zhangsan.csv
        S002_lisi.csv
        ...

or a flat file with the student id in the first line will both work.

Design notes:
  - All errors are reported per-student (one bad log does not abort the
    rest of the batch); the per-student error is captured in the summary
    row's ``status`` column.
  - Pass threshold defaults to 60 (matching the v1.3 grading engine's
    "pass" band) and is configurable.
  - The summary CSV is written with ``csv.writer`` and LF line endings
    so it imports cleanly into Excel / WPS表格.
  - v1.7 also writes a printable ``class_summary.html`` overview.
"""
from __future__ import annotations

import csv
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .flightlog import parse_csv, parse_mavplan_json, FlightLog
from .grade import grade_flight, GradeResult
from .i18n import t
from .report_html import render_report
from .taskspec import TaskSpec


# Pass threshold below which the student is marked FAIL in the summary.
DEFAULT_PASS_SCORE = 60.0


# ----------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------

@dataclass
class StudentRow:
    """One row from the roster CSV plus its result, if grading succeeded."""
    student_id: str
    name: str
    extras: dict[str, str] = field(default_factory=dict)
    score: Optional[float] = None
    passed: Optional[bool] = None
    status: str = "pending"   # "ok" | "skipped" | "error: ..."
    deductions: dict[str, float] = field(default_factory=dict)
    comment: str = ""
    report_path: Optional[str] = None


@dataclass
class ClassResult:
    """The aggregate output of one ``batch_grade`` invocation."""
    task_name: str
    pass_threshold: float
    students: List[StudentRow] = field(default_factory=list)  # type: ignore[name-defined]

    def summary_counts(self) -> dict[str, int]:
        ok = sum(1 for s in self.students if s.status == "ok")
        fail = sum(1 for s in self.students if s.passed is False)
        passed = sum(1 for s in self.students if s.passed is True)
        skipped = sum(1 for s in self.students if s.status not in ("ok",))
        return {
            "total": len(self.students),
            "graded": ok,
            "passed": passed,
            "failed": fail,
            "skipped_or_error": skipped,
        }

    def pass_rate(self) -> float:
        graded = [s for s in self.students if s.score is not None]
        if not graded:
            return 0.0
        passed = sum(1 for s in graded if s.passed)
        return passed / len(graded)


# ----------------------------------------------------------------------
# Roster I/O
# ----------------------------------------------------------------------

_REQUIRED_ROSTER_COLUMNS = ("student_id", "name")


def load_roster(path: Path) -> List[StudentRow]:  # type: ignore[name-defined]
    """Load a roster CSV.  Returns one ``StudentRow`` per row.

    Raises:
        FileNotFoundError: roster file does not exist.
        ValueError: required columns (``student_id``, ``name``) missing.
    """
    if not Path(path).is_file():
        raise FileNotFoundError(f"roster file not found: {path}")
    rows: List[StudentRow] = []  # type: ignore[name-defined]
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("roster CSV has no header row")
        missing = [c for c in _REQUIRED_ROSTER_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ValueError(
                f"roster CSV missing required columns: {missing}. "
                f"Found: {reader.fieldnames}"
            )
        for raw in reader:
            sid = (raw.get("student_id") or "").strip()
            name = (raw.get("name") or "").strip()
            if not sid:
                continue
            extras = {k: v for k, v in raw.items() if k not in _REQUIRED_ROSTER_COLUMNS}
            rows.append(StudentRow(student_id=sid, name=name, extras=extras))
    return rows


# ----------------------------------------------------------------------
# Flight log discovery
# ----------------------------------------------------------------------

def find_log_for_student(student_id: str, logs_dir: Path) -> Optional[Path]:
    """Find the first flight log file matching ``student_id``.

    Matching rules (in priority order):
      1. Filename starts with ``<student_id>`` (with optional separator).
      2. Filename contains ``<student_id>`` as a word.
      3. ``.json`` log whose ``student_id`` field matches.

    Returns ``None`` when no candidate is found.
    """
    if not logs_dir.is_dir():
        return None
    sid = student_id.strip()
    sid_lower = sid.lower()
    candidates: list[Path] = []

    for ext in (".csv", ".json"):
        for p in sorted(logs_dir.glob(f"*{ext}")):
            stem_lower = p.stem.lower()
            if stem_lower.startswith(sid_lower):
                return p
            # Treat _, -, space as word separators for matching.
            tokens = re.split(r"[_\-\s]+", stem_lower)
            if sid_lower in tokens:
                candidates.append(p)

    if candidates:
        return candidates[0]

    # Last resort: scan JSON headers for a matching ``student_id`` field.
    for p in sorted(logs_dir.glob("*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                header = json.load(f)
            if isinstance(header, dict) and str(header.get("student_id", "")).strip() == sid:
                return p
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _load_flight_log(path: Path) -> FlightLog:
    """Load a flight log by file extension."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return parse_mavplan_json(path)
    return parse_csv(path)


# ----------------------------------------------------------------------
# Per-student grading
# ----------------------------------------------------------------------

def grade_one_student(
    student: StudentRow,
    task: TaskSpec,
    log_path: Path,
    out_dir: Path,
    pass_threshold: float = DEFAULT_PASS_SCORE,
) -> StudentRow:
    """Grade one student's flight log; populate ``student`` in place.

    On any error, sets ``student.status`` to ``"error: <message>"`` so
    the rest of the batch can continue.
    """
    student.report_path = None
    student.deductions = {}
    student.comment = ""
    try:
        flight = _load_flight_log(log_path)
        result: GradeResult = grade_flight(task, flight, student=student.name or student.student_id)

        # Per-category deduction totals for the summary CSV.
        category_totals: dict[str, float] = {}
        for d in result.deductions:
            category_totals[d.category] = category_totals.get(d.category, 0.0) + d.points
        student.deductions = category_totals
        student.score = result.score
        student.passed = result.score >= pass_threshold
        student.comment = result.comment

        # Per-student HTML report.
        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / f"{student.student_id}.html"
        render_report(
            task=task,
            result=result,
            flight=flight,
            output_path=str(html_path),
        )
        student.report_path = str(html_path)
        student.status = "ok"
    except Exception as exc:  # noqa: BLE001 — keep batch going
        student.status = f"error: {exc}"
        student.passed = None
        student.score = None
    return student


# ----------------------------------------------------------------------
# Batch driver
# ----------------------------------------------------------------------

def batch_grade(
    roster_path: Path,
    logs_dir: Path,
    task_path: Path,
    out_dir: Path,
    pass_threshold: float = DEFAULT_PASS_SCORE,
) -> ClassResult:
    """Grade every student in the roster against ``task_path``.

    Returns a ``ClassResult`` whose ``students`` list is populated in
    roster order.  Per-student HTML reports are written under ``out_dir``
    and a ``class_summary.csv`` is also written there.
    """
    task = TaskSpec.load(task_path)
    roster = load_roster(roster_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = ClassResult(task_name=task.name, pass_threshold=pass_threshold)
    for student in roster:
        log = find_log_for_student(student.student_id, logs_dir)
        if log is None:
            student.status = "skipped: no log file"
            student.passed = None
            student.score = None
        else:
            grade_one_student(student, task, log, out_dir, pass_threshold)
        result.students.append(student)

    write_summary_csv(result, out_dir)
    write_class_summary_html(result, out_dir)
    return result


# ----------------------------------------------------------------------
# Summary CSV
# ----------------------------------------------------------------------

_SUMMARY_HEADER = [
    "student_id",
    "name",
    "score",
    "passed",
    "status",
    "comment",
    "report_path",
]


def write_summary_csv(result: ClassResult, out_dir: Path) -> Path:
    """Write ``class_summary.csv`` into ``out_dir`` and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "class_summary.csv"

    # Gather all extra columns across the roster so the CSV is wide enough.
    extras_keys: list[str] = []
    seen: set[str] = set()
    for s in result.students:
        for k in s.extras.keys():
            if k not in seen:
                seen.add(k)
                extras_keys.append(k)

    header = list(_SUMMARY_HEADER) + extras_keys

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        for s in result.students:
            passed_str = "" if s.passed is None else ("true" if s.passed else "false")
            score_str = "" if s.score is None else f"{s.score:.1f}"
            row = [
                s.student_id,
                s.name,
                score_str,
                passed_str,
                s.status,
                s.comment,
                s.report_path or "",
            ]
            for k in extras_keys:
                row.append(s.extras.get(k, ""))
            writer.writerow(row)
    return path


def write_class_summary_html(result: ClassResult, out_dir: Path) -> Path:
    """Write a printable class overview ``class_summary.html`` (v1.7)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "class_summary.html"
    path.write_text(render_class_summary_html(result, out_dir), encoding="utf-8")
    return path


def render_class_summary_html(result: ClassResult, out_dir: Optional[Path] = None) -> str:
    """Render the class overview HTML string (self-contained, offline)."""
    e = html.escape
    counts = result.summary_counts()
    graded = [s for s in result.students if s.score is not None]
    scores = [s.score for s in graded if s.score is not None]
    avg = sum(scores) / len(scores) if scores else 0.0
    hi = max(scores) if scores else 0.0
    lo = min(scores) if scores else 0.0
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _level(score: Optional[float], passed: Optional[bool]) -> tuple[str, str]:
        if score is None:
            return "—", "level-na"
        if score >= 90:
            return "优秀", "level-a"
        if score >= 80:
            return "良好", "level-b"
        if passed:
            return "合格", "level-c"
        return "不合格", "level-d"

    rows_html = []
    for s in result.students:
        level, cls = _level(s.score, s.passed)
        score_str = "—" if s.score is None else f"{s.score:.1f}"
        top_ded = ""
        if s.deductions:
            top = sorted(s.deductions.items(), key=lambda kv: -kv[1])[:2]
            top_ded = "；".join(f"{k} -{v:.0f}" for k, v in top)
        report_link = ""
        if s.report_path:
            name = Path(s.report_path).name
            report_link = f'<a href="{e(name)}">{e(name)}</a>'
        status = e(s.status)
        rows_html.append(
            f"<tr><td>{e(s.student_id)}</td><td>{e(s.name)}</td>"
            f"<td class=\"num\">{score_str}</td>"
            f"<td class=\"level {cls}\">{level}</td>"
            f"<td>{status}</td><td>{e(top_ded)}</td><td>{report_link}</td></tr>"
        )

    cards = "".join(
        f'<div class="metric"><div class="metric-label">{lab}</div>'
        f'<div class="metric-value">{val}</div></div>'
        for lab, val in [
            ("总人数", str(counts["total"])),
            ("已判分", str(counts["graded"])),
            ("通过", str(counts["passed"])),
            ("不通过", str(counts["failed"])),
            ("平均分", f"{avg:.1f}"),
            ("最高/最低", f"{hi:.0f} / {lo:.0f}"),
        ]
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>班级成绩汇总 · {e(result.task_name)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f2f4f8; color: #222; padding: 24px; }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  .page {{ background: #fff; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.08); padding: 28px 32px; }}
  h1 {{ font-size: 22px; color: #1a3c6e; margin-bottom: 4px; }}
  h2 {{ font-size: 15px; color: #555; font-weight: 400; margin: 4px 0 16px; }}
  .sub {{ color: #777; font-size: 12px; margin-bottom: 16px; }}
  .metrics {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin: 14px 0 18px; }}
  .metric {{ background: #f7f9fc; border: 1px solid #e3e8f0; border-radius: 8px; padding: 10px; text-align: center; }}
  .metric-label {{ font-size: 11px; color: #667; }}
  .metric-value {{ font-size: 18px; font-weight: 700; color: #1a3c6e; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ border: 1px solid #dde3ec; padding: 7px 9px; text-align: left; }}
  th {{ background: #f0f4fa; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .level-a {{ background: #27ae60; color: #fff; text-align: center; font-weight: 700; }}
  .level-b {{ background: #2980b9; color: #fff; text-align: center; font-weight: 700; }}
  .level-c {{ background: #f39c12; color: #fff; text-align: center; font-weight: 700; }}
  .level-d {{ background: #e74c3c; color: #fff; text-align: center; font-weight: 700; }}
  .level-na {{ color: #99a; text-align: center; }}
  a {{ color: #1a3c6e; }}
  .footer {{ text-align: center; color: #99a; font-size: 12px; margin-top: 22px; }}
  @media print {{ body {{ background: #fff; padding: 0; }} .page {{ box-shadow: none; }} }}
</style>
</head>
<body>
<div class="wrap">
  <div class="page">
    <h1>班级成绩汇总</h1>
    <h2>任务：{e(result.task_name)} · 及格线 {result.pass_threshold:.0f} 分</h2>
    <div class="sub">生成时间：{e(now)} · mavplan v1.7 · 可打印</div>
    <div class="metrics">{cards}</div>
    <table>
      <thead><tr>
        <th>学号</th><th>姓名</th><th>分数</th><th>等级</th><th>状态</th><th>主要扣分</th><th>个人报告</th>
      </tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>
    <div class="footer">本汇总由 mavplan 生成；个人报告为同目录下的独立 HTML 文件。</div>
  </div>
</div>
</body>
</html>
"""


# ----------------------------------------------------------------------
# Class summary (CLI-facing reader)
# ----------------------------------------------------------------------

def read_summary(out_dir: Path) -> List[dict[str, str]]:  # type: ignore[name-defined]
    """Read ``class_summary.csv`` from a previous batch run."""
    path = out_dir / "class_summary.csv"
    if not path.is_file():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def class_summary_text(out_dir: Path) -> str:
    """Render a human-readable class summary suitable for CLI printing."""
    rows = read_summary(out_dir)
    if not rows:
        return "未找到汇总文件 class_summary.csv"

    n_total = len(rows)
    n_graded = sum(1 for r in rows if r.get("status") == "ok")
    scores = [float(r["score"]) for r in rows if r.get("score")]
    n_pass = sum(1 for r in rows if r.get("passed") == "true")
    n_fail = n_graded - n_pass

    lines: list[str] = []
    lines.append(f"{t('report.batch_done')}:")
    lines.append(f"  总人数: {n_total}")
    lines.append(f"  已判分: {n_graded}")
    if scores:
        lines.append(f"  平均分: {sum(scores) / len(scores):.1f}")
        lines.append(f"  最高分: {max(scores):.1f}")
        lines.append(f"  最低分: {min(scores):.1f}")
    lines.append(f"  通过: {n_pass}")
    lines.append(f"  不通过: {n_fail}")
    return "\n".join(lines)