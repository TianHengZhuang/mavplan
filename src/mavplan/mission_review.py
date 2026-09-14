"""One-click mission review: pre / in-flight / post analysis (v1.16)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from .fleet import Fleet, assign_formation_offsets
from .mission import Mission
from .nofly import PreflightParams, preflight_check
from .taskspec import Zone

Verdict = Literal["pass", "conditional", "fail"]


@dataclass
class ReviewContext:
    mission: Mission
    fleet: Optional[Fleet] = None
    zones: list[Zone] = field(default_factory=list)
    params: Optional[PreflightParams] = None
    generated_at: Optional[datetime] = None


def _verdict_from_checks(checks: list[dict]) -> tuple[Verdict, str]:
    errors = sum(1 for c in checks if c.get("level") == "error")
    warnings = sum(1 for c in checks if c.get("level") == "warning")
    if errors:
        return "fail", "不建议放飞：存在错误级问题"
    if warnings:
        return "conditional", "有条件通过：存在需确认的警告"
    return "pass", "通过：计划检查未发现阻断项"


def _fmt_km(m: float) -> str:
    return f"{m / 1000:.2f} km" if m >= 1000 else f"{m:.0f} m"


def _fmt_dur(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m} 分 {s:02d} 秒" if m else f"{s} 秒"


def build_pre_flight_section(mission: Mission, fleet: Optional[Fleet], checks: list[dict]) -> dict[str, Any]:
    wps = [wp for wp in mission.waypoints() if getattr(wp, "command", 3) in (3, 16, 22) or True]
    nav = [wp for wp in mission.waypoints() if getattr(wp, "command", 3) in (3, 16, 22)]
    altitudes = [wp.alt for wp in nav] or [wp.alt for wp in mission.waypoints()]
    verdict, verdict_text = _verdict_from_checks(checks)
    bullets: list[str] = []
    bullets.append(f"结论：**{verdict_text}**")
    bullets.append(
        f"航线：{len(nav)} 个导航点 / 共 {len(mission.waypoints())} 项，"
        f"约 {_fmt_km(mission.total_distance())}，预计 {_fmt_dur(mission.estimated_duration())}"
    )
    if altitudes:
        bullets.append(f"高度带：{min(altitudes):.0f}–{max(altitudes):.0f} m")
    if fleet:
        bullets.append(f"机队：{fleet.count} 架 — " + "；".join(f"{d.name}({d.role}/{d.status})" for d in fleet.drones))
        if fleet.count > 1:
            offsets = assign_formation_offsets(fleet)
            wing = [o for o in offsets if o["slot"] != 0]
            if wing:
                spacing = abs(wing[0]["offset_east_m"])
                bullets.append(f"编队建议：横向间距 ≥ {spacing:.0f} m（主机居中）")
    else:
        bullets.append("机队：未配置（按单机主机处理）")
    errors = [c for c in checks if c.get("level") == "error"]
    warnings = [c for c in checks if c.get("level") == "warning"]
    if errors:
        bullets.append("阻断项：" + "；".join(c.get("message", "") for c in errors[:5]))
    if warnings:
        bullets.append("提示项：" + "；".join(c.get("message", "") for c in warnings[:5]))
    if verdict == "pass":
        bullets.append("建议：完成例行检查后按计划放飞。")
    elif verdict == "conditional":
        bullets.append("建议：消除或确认全部警告后再放飞；确认电池与空域许可。")
    else:
        bullets.append("建议：修正错误级问题后重新预检。")
    return {
        "title": "任务前分析",
        "verdict": verdict,
        "bullets": bullets,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def build_in_flight_section(mission: Mission, fleet: Optional[Fleet]) -> dict[str, Any]:
    wps = mission.waypoints()
    bullets: list[str] = []
    if not wps:
        return {"title": "任务中分析", "bullets": ["无航点，无法生成飞行中要点。"]}
    # longest leg
    longest = 0.0
    longest_pair = (0, 1)
    max_climb = 0.0
    climb_pair = (0, 1)
    for i in range(1, len(wps)):
        prev, cur = wps[i - 1], wps[i]
        # rough distance using mission helpers if available
        try:
            from .taskspec import haversine_m

            dist = haversine_m(prev.lat, prev.lon, cur.lat, cur.lon)
        except Exception:
            dist = abs(cur.lat - prev.lat) * 111320 + abs(cur.lon - prev.lon) * 100000
        if dist > longest:
            longest = dist
            longest_pair = (i - 1, i)
        climb = abs(cur.alt - prev.alt)
        if climb > max_climb:
            max_climb = climb
            climb_pair = (i - 1, i)
    bullets.append(
        f"关键段：最长航段 WP{longest_pair[0]}→WP{longest_pair[1]}（{_fmt_km(longest)}）；"
        f"最大高度变化 WP{climb_pair[0]}→WP{climb_pair[1]}（{max_climb:.0f} m）"
    )
    altitudes = [wp.alt for wp in wps]
    bullets.append(f"高度走廊：保持 {min(altitudes):.0f}–{max(altitudes):.0f} m，注意限高与转弯半径")
    speeds = [wp.speed for wp in wps if wp.speed > 0]
    if speeds:
        bullets.append(f"速度：巡航约 {sum(speeds) / len(speeds):.1f} m/s（各点差异 {max(speeds) - min(speeds):.1f} m/s）")
    bullets.append("应急：确认失联返航点 HOME；进入景区/机场相关区前复核禁飞清单")
    if fleet and fleet.count > 1:
        bullets.append("编队：保持横向间隔，避免同时切入同一转弯内侧")
    return {"title": "任务中分析", "bullets": bullets}


def build_post_flight_section(
    mission: Mission,
    fleet: Optional[Fleet],
    checks: list[dict],
) -> dict[str, Any]:
    bullets: list[str] = []
    bullets.append(
        "计划基线：命中率、最大高度带、禁飞区零侵入、拍照触发是否按计划执行"
    )
    bullets.append(
        f"归档建议：任务 JSON / WPL / 简报 / 飞行日志 CSV（{_fmt_km(mission.total_distance())} / "
        f"{_fmt_dur(mission.estimated_duration())}）"
    )
    if any(c.get("code") == "no_fly_enter" for c in checks):
        bullets.append("复盘重点：本次计划存在禁飞侵入，必须解释处置或改航")
    else:
        bullets.append("复盘重点：编队间距维持、实际高度带是否落在计划走廊")
    if fleet:
        bullets.append("机队复盘：" + "、".join(d.name for d in fleet.drones))
    bullets.append("后续：将日志导入 analyze compare 做计划 vs 实测对比")
    return {"title": "任务后分析", "bullets": bullets}


def build_mission_review(ctx: ReviewContext) -> dict[str, Any]:
    """Structured three-phase review document."""
    checks = preflight_check(ctx.mission, ctx.zones or [], ctx.params)
    generated = ctx.generated_at or datetime.now(timezone.utc)
    pre = build_pre_flight_section(ctx.mission, ctx.fleet, checks)
    mid = build_in_flight_section(ctx.mission, ctx.fleet)
    post = build_post_flight_section(ctx.mission, ctx.fleet, checks)
    return {
        "schema": "mavplan.review/1",
        "mission_name": ctx.mission.name,
        "generated_at": generated.isoformat(),
        "drone_count": ctx.fleet.count if ctx.fleet else 1,
        "verdict": pre["verdict"],
        "sections": [pre, mid, post],
        "checks": checks,
    }


def render_review_markdown(review: dict[str, Any]) -> str:
    lines = [
        f"# 任务一键总结 · {review.get('mission_name') or 'Mission'}",
        f"生成时间：{review.get('generated_at', '')} · 机队：{review.get('drone_count', 1)} 架",
        "",
    ]
    for section in review.get("sections") or []:
        lines.append(f"## {section.get('title')}")
        for b in section.get("bullets") or []:
            lines.append(f"- {b}")
        lines.append("")
    return "\n".join(lines)
