"""Internationalization (v1.6 training operations).

Lightweight, dependency-free translation layer: a small zh-CN / en
dictionary covers the user-visible strings (help, errors, status, reports,
grade comments). The active language is selected via, in priority order:

1. Explicit ``set_language(...)`` call (used by tests and CLI ``--lang``).
2. ``MAVPLAN_LANG`` environment variable.
3. ``LANG`` / ``LANGUAGE`` environment variable (e.g. ``zh_CN.UTF-8``).
4. Fallback to ``zh-CN`` (mavplan's primary audience is Chinese CAAC
   training operators).

API:
    t("key")           -> translated string for the active language
    t("key", *args)    -> translated string formatted with ``%`` style
    set_language("en") -> switch active language (returns the new active lang)
    get_language()     -> currently active language code
    available()        -> list of supported language codes

A missing key returns the key itself in angle brackets (e.g. ``<foo>``)
so untranslated text never silently disappears during development.

Design notes:
  - Pure data + one helper; no logging, no globals beyond ``_ACTIVE``.
  - All strings are ASCII-only in the source (zh-CN uses UTF-8 literals).
  - Tests patch ``_ACTIVE`` directly to verify both languages.
"""
from __future__ import annotations

import os
from typing import Optional

# Supported language codes.
ZH = "zh-CN"
EN = "en"
SUPPORTED = (ZH, EN)
DEFAULT = ZH

_ACTIVE: str = DEFAULT  # mutated via set_language(); read by get_language()


# ----------------------------------------------------------------------
# Translation table.
#
# Convention: every key is uppercase_snake_case and identifies a phrase,
# not a fragment. Callers compose longer text from multiple t() calls
# when needed.  Some strings carry positional %s placeholders that are
# filled by the caller.
# ----------------------------------------------------------------------

_TRANSLATIONS: dict[str, dict[str, str]] = {
    ZH: {
        # Global / help
        "app.tagline": "MAVLink 任务规划器——航线规划、模式生成、模拟与教学评估",
        "app.description": "无人机航线规划、模式生成、模拟、判分一体化教学工具",
        "app.usage": "用法: mavplan [选项] [命令] [参数]...",
        "app.options": "选项:",
        "app.commands": "命令:",
        "app.lang_help": "界面语言 (zh-CN|en)",
        "app.version": "mavplan 版本",
        # Common verbs
        "common.ok": "✓",
        "common.fail": "✗",
        "common.warning": "警告",
        "common.error": "错误",
        "common.saved": "已保存",
        "common.loaded": "已加载",
        "common.failed": "失败",
        "common.skipped": "跳过",
        "common.required": "必选",
        # Mission commands
        "cmd.mission": "任务管理(导入/导出/航点)",
        "cmd.waypoint": "航点操作(增删改查)",
        "cmd.pattern": "自动航迹(lawnmower/orbit/多边形扫描)",
        "cmd.simulate": "仿真(能量估算/风扰/禁飞区)",
        "cmd.analyze": "飞行日志分析(对比/统计)",
        "cmd.link": "MAVLink 飞控链路(上传/下载)",
        "cmd.template": "KML 模板与导入",
        "cmd.export": "导出(MAVLink/.plan/WPL/KML/CSV)",
        "cmd.task": "教学任务书(生成/校验/导出)",
        "cmd.grade": "判分(单学员/批量/汇总)",
        "cmd.scenario": "场景预设(列表/详情/生成任务)",
        "cmd.class": "班级汇总(批量判分结果统计)",
        # Mission sub
        "mission.save": "保存当前任务到 JSON 文件",
        "mission.load": "从 JSON 文件加载任务",
        "mission.import": "自动探测格式导入(mavplan/wpl/plan)",
        "mission.export": "按指定格式导出任务",
        "mission.list": "列出任务中的所有航点",
        "mission.validate": "校验当前任务",
        "mission.check": "安全预检(转弯半径/禁飞区/续航)",
        # Waypoint sub
        "wp.add": "向当前任务新增一个航点",
        "wp.remove": "从任务中移除指定序号航点",
        "wp.list": "列出任务中的所有航点",
        "wp.action": "在指定航点后插入一个 DO_* 动作",
        # Pattern sub
        "pat.lawnmower": "生成 lawnmower 扫描航线",
        "pat.polygon": "生成多边形扫描航线",
        "pat.orbit": "生成圆形环绕航线",
        # Simulate sub
        "sim.run": "完整仿真(能量+风扰+禁飞区)",
        "sim.battery": "估算电池续航",
        "sim.geofence": "检查围栏与禁飞区",
        "sim.with_tol": "插入起飞/降落航点",
        "sim.lost_link": "演示链路丢失自动返航",
        # Analyze sub
        "ana.log": "解析飞行日志输出统计",
        "ana.kml": "飞行日志转 KML",
        "ana.compare": "飞行日志与计划航线对比",
        # Link sub
        "link.status": "查询飞控链路状态",
        "link.upload": "上传任务到飞控",
        "link.download": "从飞控下载任务",
        # Template sub
        "tpl.list": "列出内置 KML 模板",
        "tpl.load": "载入模板到当前任务",
        "tpl.import_kml": "从 KML 文件导入为任务",
        "tpl.export": "导出全部模板为 JSON",
        # Export sub
        "exp.mavlink": "导出为 MAVLink WPL 文件",
        "exp.plan": "导出为 QGroundControl .plan 文件",
        "exp.wpl": "导出为 Mission Planner WPL 文件",
        "exp.kml": "导出为 KML 文件(Google Earth)",
        "exp.csv": "导出为 CSV 文件",
        # Task sub
        "task.new": "创建空白任务书",
        "task.generate": "按难度随机生成任务书",
        "task.validate": "校验任务书参数",
        "task.show": "显示任务书详情",
        "task.save": "保存任务书到 JSON",
        # Grade sub
        "grade.run": "对单个飞行日志判分",
        "grade.batch": "批量判分(整班学员)",
        "grade.summary": "汇总批量判分结果",
        # Scenario sub
        "scenario.list": "列出全部预设场景",
        "scenario.show": "查看指定场景详情",
        "scenario.run": "根据场景生成任务书与任务",
        # Class sub
        "class.summary": "汇总批量判分结果",
        # Reports / messages
        "report.generated": "报告已生成",
        "report.path": "路径",
        "report.score_label": "得分",
        "report.student": "学员",
        "report.task": "任务",
        "report.no_logs": "未找到日志文件",
        "report.batch_done": "批量判分完成",
        "report.summary_csv": "汇总 CSV 已生成",
        "report.html_count": "已生成 HTML 报告",
        # Errors
        "err.coord_invalid": "坐标非法: 纬度 [-90, 90] 经度 [-180, 180]",
        "err.file_not_found": "文件不存在",
        "err.format_unknown": "无法识别的文件格式",
        "err.mission_empty": "任务为空",
        "err.task_invalid": "任务书参数非法",
        "err.roster_missing": "班级名册文件不存在",
        "err.logs_dir_missing": "日志目录不存在",
        "err.lang_unsupported": "不支持的语言代码",
        # Scenario templates (used by scenario list)
        "scen.rectangle_patrol": "矩形巡检",
        "scen.corridor_transit": "走廊穿越",
        "scen.powerline_inspection": "电力巡线",
        "scen.agri_spraying": "植保作业",
        "scen.search_rescue": "应急搜救",
        "scen.bridge_inspection": "桥梁检测",
        "scen.logistics_delivery": "物流配送",
        "scen.lost_link_demo": "链路丢失演示",
        # Grade comments
        "grade.comment.excellent": "表现优秀,继续保持",
        "grade.comment.good": "表现良好,部分细节可优化",
        "grade.comment.pass": "基本合格,扣分项需注意",
        "grade.comment.fail": "未通过,需针对扣分项加强训练",
        # Welcome (top of --help output)
        "welcome.title": "mavplan — 无人机航线规划与教学评估工具",
        "welcome.intro": "支持 PX4 / ArduPilot 及所有 MAVLink 兼容飞控。",
    },
    EN: {
        "app.tagline": "MAVLink mission planner — routes, patterns, simulation, training",
        "app.description": "Drone mission planning, pattern generation, simulation, and grading in one tool",
        "app.usage": "Usage: mavplan [OPTIONS] COMMAND [ARGS]...",
        "app.options": "Options:",
        "app.commands": "Commands:",
        "app.lang_help": "Interface language (zh-CN|en)",
        "app.version": "mavplan version",
        "common.ok": "OK",
        "common.fail": "FAIL",
        "common.warning": "Warning",
        "common.error": "Error",
        "common.saved": "saved",
        "common.loaded": "loaded",
        "common.failed": "failed",
        "common.skipped": "skipped",
        "common.required": "required",
        "cmd.mission": "Manage mission (import/export/waypoints)",
        "cmd.waypoint": "Manage waypoints",
        "cmd.pattern": "Generate patterns (lawnmower/orbit/polygon)",
        "cmd.simulate": "Simulate (energy/wind/geofence)",
        "cmd.analyze": "Analyze flight logs (compare/stats)",
        "cmd.link": "MAVLink link (upload/download)",
        "cmd.template": "KML templates and import",
        "cmd.export": "Export (MAVLink/.plan/WPL/KML/CSV)",
        "cmd.task": "Training tasks (generate/validate/export)",
        "cmd.grade": "Grade flights (single/batch/summary)",
        "cmd.scenario": "Scenario presets (list/show/run)",
        "cmd.class": "Class summary (batch grading roll-up)",
        "mission.save": "Save current mission to a JSON file",
        "mission.load": "Load mission from a JSON file",
        "mission.import": "Auto-detect and import (mavplan/wpl/plan)",
        "mission.export": "Export the mission in the requested format",
        "mission.list": "List all waypoints in the mission",
        "mission.validate": "Validate the current mission",
        "mission.check": "Safety preflight (turns/zones/battery)",
        "wp.add": "Add a waypoint to the current mission",
        "wp.remove": "Remove a waypoint by its sequence number",
        "wp.list": "List all waypoints in the mission",
        "wp.action": "Insert a DO_* action after a waypoint",
        "pat.lawnmower": "Generate a lawn-mower sweep",
        "pat.polygon": "Generate a polygon scan",
        "pat.orbit": "Generate a circular orbit",
        "sim.run": "Full simulation (energy + wind + geofence)",
        "sim.battery": "Estimate battery endurance",
        "sim.geofence": "Check geofence and no-fly zones",
        "sim.with_tol": "Insert takeoff and landing waypoints",
        "sim.lost_link": "Demonstrate lost-link return-to-home",
        "ana.log": "Parse a flight log and print stats",
        "ana.kml": "Convert a flight log to KML",
        "ana.compare": "Compare a flight log against the planned route",
        "link.status": "Query the autopilot link status",
        "link.upload": "Upload the mission to the autopilot",
        "link.download": "Download the mission from the autopilot",
        "tpl.list": "List the bundled KML templates",
        "tpl.load": "Load a template into the current mission",
        "tpl.import_kml": "Import a KML file as a mission",
        "tpl.export": "Export all templates as JSON",
        "exp.mavlink": "Export as MAVLink WPL file",
        "exp.plan": "Export as QGroundControl .plan file",
        "exp.wpl": "Export as Mission Planner WPL file",
        "exp.kml": "Export as KML file (Google Earth)",
        "exp.csv": "Export as CSV file",
        "task.new": "Create a blank task spec",
        "task.generate": "Generate a task spec by difficulty",
        "task.validate": "Validate a task spec",
        "task.show": "Show task spec details",
        "task.save": "Save a task spec to JSON",
        "grade.run": "Grade a single flight log",
        "grade.batch": "Batch grade a whole class",
        "grade.summary": "Summarize batch grading results",
        "scenario.list": "List all preset scenarios",
        "scenario.show": "Show details of a scenario",
        "scenario.run": "Generate a task spec + mission from a scenario",
        "class.summary": "Summarize batch grading results",
        "report.generated": "Report generated",
        "report.path": "path",
        "report.score_label": "Score",
        "report.student": "Student",
        "report.task": "Task",
        "report.no_logs": "no flight logs found",
        "report.batch_done": "batch grading done",
        "report.summary_csv": "summary CSV written",
        "report.html_count": "HTML reports written",
        "err.coord_invalid": "Invalid coordinates: lat [-90, 90] lon [-180, 180]",
        "err.file_not_found": "File not found",
        "err.format_unknown": "Unrecognized file format",
        "err.mission_empty": "Mission is empty",
        "err.task_invalid": "Invalid task spec",
        "err.roster_missing": "Roster file not found",
        "err.logs_dir_missing": "Logs directory not found",
        "err.lang_unsupported": "Unsupported language code",
        "scen.rectangle_patrol": "Rectangle patrol",
        "scen.corridor_transit": "Corridor transit",
        "scen.powerline_inspection": "Power-line inspection",
        "scen.agri_spraying": "Agricultural spraying",
        "scen.search_rescue": "Search and rescue",
        "scen.bridge_inspection": "Bridge inspection",
        "scen.logistics_delivery": "Logistics delivery",
        "scen.lost_link_demo": "Lost-link demo",
        "grade.comment.excellent": "Excellent work — keep it up",
        "grade.comment.good": "Good — minor improvements possible",
        "grade.comment.pass": "Pass — pay attention to deductions",
        "grade.comment.fail": "Fail — focus on the deduction areas",
        "welcome.title": "mavplan — drone mission planning & training toolkit",
        "welcome.intro": "Works with PX4, ArduPilot, and any MAVLink-compatible autopilot.",
    },
}


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def set_language(lang: str) -> str:
    """Set the active language; returns the (possibly-fallen) value used."""
    if lang in SUPPORTED:
        _ACTIVE = lang  # noqa: F841 (rebind module global)
        globals()["_ACTIVE"] = lang
        return lang
    # Try common aliases
    norm = lang.replace("_", "-").lower()
    if norm.startswith("zh"):
        globals()["_ACTIVE"] = ZH
        return ZH
    if norm.startswith("en"):
        globals()["_ACTIVE"] = EN
        return EN
    raise ValueError(f"Unsupported language: {lang}")


def get_language() -> str:
    """Return the currently active language code."""
    return globals().get("_ACTIVE", DEFAULT)


def available() -> tuple[str, ...]:
    """Tuple of supported language codes."""
    return SUPPORTED


def detect_from_env() -> str:
    """Pick the best language from environment variables (no side effects)."""
    env = (
        os.environ.get("MAVPLAN_LANG")
        or os.environ.get("LANG")
        or os.environ.get("LANGUAGE")
        or ""
    )
    norm = env.replace("_", "-").lower()
    if norm.startswith("zh"):
        return ZH
    if norm.startswith("en"):
        return EN
    return DEFAULT


def init_from_env() -> str:
    """Initialize the active language from environment variables."""
    chosen = detect_from_env()
    globals()["_ACTIVE"] = chosen
    return chosen


def t(key: str, *args: object) -> str:
    """Translate a key using the active language.

    Positional ``*args`` are interpolated via ``str % args`` so the same
    key can carry different values across calls (e.g. ``t("file.saved",
    path)``).

    A missing key falls back to:
        1. The English entry (when the active language isn't English)
        2. The key wrapped in angle brackets so untranslated strings are
           obvious during development.
    """
    lang = get_language()
    table = _TRANSLATIONS.get(lang, {})
    text = table.get(key)
    if text is None and lang != EN:
        text = _TRANSLATIONS[EN].get(key)
    if text is None:
        return f"<{key}>"
    if args:
        try:
            return text % args
        except (TypeError, ValueError):
            # Caller passed wrong number of args; return raw text rather
            # than raising — a translation failure must not crash the CLI.
            return text
    return text


def reset_for_test(lang: Optional[str] = None) -> None:
    """Reset the module to a known language. Intended for unit tests."""
    globals()["_ACTIVE"] = lang if lang is not None else DEFAULT


# Eagerly initialize from environment so importing the module picks the
# right language for the current shell.  ``init_from_env()`` is also
# idempotent and safe to call again from the CLI entry point.
init_from_env()