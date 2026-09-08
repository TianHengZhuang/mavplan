"""HTML score report renderer (v1.3 teaching suite).

Single-file, self-contained HTML report: student name, task brief table,
trajectory-vs-plan overlay (inline SVG, offline), altitude profile, score,
per-category deduction table and Chinese comment. No external assets, no
JavaScript dependencies beyond a tiny inline script for toggling layers.
"""
from __future__ import annotations

import html
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

from .flightlog import FlightLog
from .grade import GradeResult
from .mission import Mission
from .taskspec import TaskSpec

_M_PER_DEG_LAT = 111_320.0
_PAD_FRAC = 0.12


def render_report(
    task: TaskSpec,
    result: GradeResult,
    flight: FlightLog,
    plan: Optional[Mission] = None,
    output_path: str = "",
    preflight_items: Optional[list] = None,
) -> str:
    """Render the score report HTML string (and write it when output_path set).

    Returns:
        The complete HTML document as text.
    """
    e = html.escape
    # ---- map geometry --------------------------------------------------
    geo = _collect_geo(task, flight, plan)
    svg_map = _svg_map(geo, e)
    svg_alt = _svg_altitude_profile(flight, task, e)

    # ---- task brief table ----------------------------------------------
    zones_txt = "、".join(
        f"{e(z.name)}（半径{z.radius_m:.0f}m）" for z in task.no_fly_zones
    ) or "无"
    checkpoints = "、".join(
        (f"{e(cp.name)}（航点，允差{cp.radius_m:.0f}m）" if cp.kind == "point"
         else f"{e(cp.name)}（区域，半径{cp.radius_m:.0f}m）")
        for cp in task.required
    ) or "无"

    rows = [
        ("任务名称", e(task.name)),
        ("任务书说明", e(task.description) or "—"),
        ("难度", e(task.difficulty)),
        ("起飞/降落点", f"{task.home[0]:.6f}, {task.home[1]:.6f}（高度 {task.home[2]:.0f}m）"),
        ("必达检查点", checkpoints),
        ("巡航高度窗口", f"{task.altitude_range[0]:.0f} ~ {task.altitude_range[1]:.0f} m"),
        ("巡航速度窗口", f"{task.speed_range[0]:.0f} ~ {task.speed_range[1]:.0f} m/s"),
        ("时间限制", f"{task.max_time_s:.0f} s"),
        ("航程限制", f"{task.max_distance_m / 1000:.2f} km"),
        ("禁飞区", zones_txt),
    ]
    brief_rows = "".join(
        f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows
    )

    # ---- metrics cards -------------------------------------------------
    m = result.metrics
    metric_cards = [
        ("实际用时", f"{m.get('flight_duration_s', 0):.0f} s", f"限 {task.max_time_s:.0f} s"),
        ("飞行航程", f"{m.get('total_distance_m', 0) / 1000:.2f} km", f"限 {task.max_distance_m / 1000:.2f} km"),
        ("最大高度", f"{m.get('max_altitude_m', 0):.0f} m", f"窗 {task.altitude_range[0]:.0f}-{task.altitude_range[1]:.0f} m"),
        ("平均速度", f"{m.get('avg_speed_mps', 0):.1f} m/s", f"窗 {task.speed_range[0]:.0f}-{task.speed_range[1]:.0f} m/s"),
    ]
    cards = "".join(
        f"""<div class="metric"><div class="metric-label">{label}</div>
        <div class="metric-value">{val}</div><div class="metric-sub">{sub}</div></div>"""
        for label, val, sub in metric_cards
    )

    # ---- deduction table ------------------------------------------------
    if result.deductions:
        rows = "".join(
            f"<tr><td>{i}</td><td>{e(d.category)}</td><td>{e(d.message)}</td>"
            f"<td class=\"num\">-{d.points:.0f}</td></tr>"
            for i, d in enumerate(result.deductions, 1)
        )
        deduction_html = (
            "<h3>扣分明细</h3>"
            "<table><thead><tr><th>#</th><th>类别</th><th>说明</th><th>扣分</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        deduction_html = "<h3>扣分明细</h3><p class=\"clean\">无违规扣分项。</p>"

    # ---- compare metrics ------------------------------------------------
    compare_html = ""
    cmp = m.get("compare_to_plan") if plan is not None else None
    if cmp and "error" not in cmp:
        compare_html = (
            "<h3>航线覆盖率（对比参考航线）</h3>"
            "<table><thead><tr><th>指标</th><th>数值</th></tr></thead><tbody>"
            f"<tr><td>计划航程</td><td>{cmp.get('plan_distance_m', 0)} m</td></tr>"
            f"<tr><td>实际航程</td><td>{cmp.get('flight_distance_m', 0)} m</td></tr>"
            f"<tr><td>覆盖率</td><td>{cmp.get('coverage_ratio', 0)}</td></tr>"
            f"<tr><td>航点命中 (50m)</td><td>{cmp.get('waypoint_hits_50m', 0)} / {cmp.get('total_plan_waypoints', 0)}</td></tr>"
            f"<tr><td>平均高度误差</td><td>{cmp.get('avg_altitude_error_m', 0)} m</td></tr>"
            "</tbody></table>"
        )

    level_class = {"优秀": "level-a", "良好": "level-b", "合格": "level-c", "不合格": "level-d"}.get(
        result.level, "level-c"
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---- preflight (v1.4 safety section) --------------------------------
    preflight_html = ""
    if preflight_items is not None:
        if preflight_items:
            rows = "".join(
                f"<tr><td>{e(it.get('code', ''))}</td>"
                f"<td>{'错误' if it.get('level') == 'error' else ('警告' if it.get('level') == 'warning' else '提示')}</td>"
                f"<td>{e(str(it.get('waypoint', '')))}</td>"
                f"<td>{e(it.get('message', ''))}</td></tr>"
                for it in preflight_items
            )
            preflight_html = (
                "<h3>飞行前安全预检（v1.4）</h3>"
                "<table><thead><tr><th>代码</th><th>级别</th><th>航点</th><th>说明</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>"
            )
        else:
            preflight_html = (
                "<h3>飞行前安全预检（v1.4）</h3>"
                "<p class=\"clean\">预检全部通过，无安全告警。</p>"
            )

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>航线规划考核成绩报告 · {e(result.student)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f2f4f8; color: #222; padding: 24px; }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  .page {{ background: #fff; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.08); padding: 32px 36px; }}
  h1 {{ font-size: 22px; color: #1a3c6e; margin-bottom: 4px; }}
  h2 {{ font-size: 15px; color: #555; font-weight: 400; margin: 4px 0 16px; }}
  h3 {{ font-size: 15px; color: #1a3c6e; margin: 26px 0 10px; border-left: 4px solid #1a3c6e; padding-left: 8px; }}
  .sub {{ color: #777; font-size: 12px; margin-bottom: 18px; }}
  .score-hero {{ display: flex; align-items: center; gap: 24px; background: linear-gradient(135deg, #1a3c6e, #2c5aa0); color: #fff; border-radius: 10px; padding: 20px 26px; margin-bottom: 10px; }}
  .score-num {{ font-size: 52px; font-weight: 700; line-height: 1; }}
  .score-right {{ flex: 1; }}
  .level-badge {{ display: inline-block; padding: 4px 16px; border-radius: 20px; font-size: 16px; font-weight: 700; }}
  .level-a {{ background: #e74c3c; }} .level-b {{ background: #e67e22; }} .level-c {{ background: #2980b9; }} .level-d {{ background: #7f8c8d; }}
  .badge {{ background: rgba(255,255,255,.18); border-radius: 20px; padding: 3px 12px; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ border: 1px solid #dde3ec; padding: 7px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #f0f4fa; width: 140px; }}
  td.num {{ text-align: right; font-weight: 600; color: #c0392b; }}
  .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 18px 0; }}
  .metric {{ background: #f7f9fc; border: 1px solid #e3e8f0; border-radius: 8px; padding: 12px; text-align: center; }}
  .metric-label {{ font-size: 12px; color: #667; }}
  .metric-value {{ font-size: 22px; font-weight: 700; color: #1a3c6e; }}
  .metric-sub {{ font-size: 11px; color: #889; margin-top: 4px; }}
  .clean {{ color: #27ae60; font-weight: 600; }}
  .comment {{ background: #fbf7ee; border: 1px solid #ecdfc0; border-radius: 8px; padding: 14px 16px; white-space: pre-wrap; font-size: 13px; line-height: 1.8; }}
  svg {{ width: 100%; height: auto; border: 1px solid #e3e8f0; border-radius: 8px; background: #fbfcfe; }}
  .legend {{ font-size: 12px; color: #556; margin-top: 6px; }}
  .footer {{ text-align: center; color: #99a; font-size: 12px; margin-top: 24px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="page">
    <h1>航线规划考核 · 成绩报告</h1>
    <h2>学员：{e(result.student)}</h2>
    <div class="sub">生成时间：{e(now)} · 任务书：{e(task.name)} · 判分引擎：mavplan v1.3</div>

    <div class="score-hero">
      <div class="score-num">{result.score:.0f}</div>
      <div class="score-right">
        <span class="level-badge {level_class}">{e(result.level)}</span>
        <span class="badge">{"通过" if result.passed else "未通过"}（及格线 60）</span>
      </div>
    </div>

    <h3>任务书</h3>
    <table><tbody>{brief_rows}</tbody></table>

    <div class="metrics">{cards}</div>

    <h3>轨迹对比</h3>
    {svg_map}
    <div class="legend">图例：<span style="color:#2c3e50;font-weight:600">■</span> 计划航线（蓝虚线） ·
      <span style="color:#e67e22;font-weight:600">■</span> 实际飞行（橙实线） ·
      <span style="color:#27ae60;font-weight:600">●</span> 必达检查点（含允差圈） ·
      <span style="color:#c0392b;font-weight:600">●</span> 禁飞区</div>

    <h3>高度剖面（实际飞行）</h3>
    {svg_alt}

    {deduction_html}
    {compare_html}
    {preflight_html}

    <h3>评语</h3>
    <div class="comment">{e(result.comment)}</div>

    <div class="footer">本报告由 mavplan 生成，用于 CAAC 无人机执照培训模拟考核教学。</div>
  </div>
</div>
</body>
</html>
"""
    if output_path:
        Path(output_path).write_text(html_doc, encoding="utf-8")
    return html_doc


# ------------------------------------------------------------------
# SVG helpers
# ------------------------------------------------------------------

def _collect_geo(task: TaskSpec, flight: FlightLog, plan: Optional[Mission]) -> dict:
    """Collect all geographic features into one namespace for map layout."""
    pts: list[tuple[float, float]] = []
    features: dict = {"home": None, "points": [], "areas": [], "zones": [], "plan": [], "flight": []}

    home = task.home
    features["home"] = (home[0], home[1])
    pts.append((home[0], home[1]))

    for cp in task.required:
        item = {"name": cp.name, "lat": cp.lat, "lon": cp.lon, "radius_m": cp.radius_m, "kind": cp.kind}
        (features["points"] if cp.kind == "point" else features["areas"]).append(item)
        pts.append((cp.lat, cp.lon))
    for z in task.no_fly_zones:
        features["zones"].append({"name": z.name, "lat": z.lat, "lon": z.lon, "radius_m": z.radius_m})
        pts.append((z.lat, z.lon))
    if plan:
        for wp in plan.waypoints():
            features["plan"].append((wp.lat, wp.lon))
            pts.append((wp.lat, wp.lon))
    for p in flight.points:
        features["flight"].append((p.lat, p.lon))
        pts.append((p.lat, p.lon))

    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    if not lats:
        return features
    features["bbox"] = (min(lats), max(lats), min(lons), max(lons))
    return features


def _project(geo: dict, lat: float, lon: float) -> tuple[float, float]:
    lat0, lat1, lon0, lon1 = geo["bbox"]
    pad_lat = max((lat1 - lat0) * _PAD_FRAC, 0.0002)
    pad_lon = max((lon1 - lon0) * _PAD_FRAC, 0.0002)
    y0, y1 = lat0 - pad_lat, lat1 + pad_lat
    x0, x1 = lon0 - pad_lon, lon1 + pad_lon
    mid_lat = math.radians((y0 + y1) / 2)
    # equirectangular with aspect compensation
    xs = (lon - x0) * math.cos(mid_lat)
    ys = (y1 - lat)
    span_x = max((x1 - x0) * math.cos(mid_lat), 1e-9)
    span_y = max(y1 - y0, 1e-9)
    return xs / span_x * 900.0, ys / span_y * 560.0


def _svg_map(geo: dict, e) -> str:
    if not geo.get("bbox"):
        return '<svg viewBox="0 0 900 560"></svg>'
    parts = []
    # plan route first (background), then zones, checkpoints, flight on top
    if geo["plan"]:
        coords = " ".join(
            f"{_project(geo, la, lo)[0]:.1f},{_project(geo, la, lo)[1]:.1f}"
            for la, lo in geo["plan"]
        )
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="#2c3e50" stroke-width="2.5" '
            f'stroke-dasharray="7,4" stroke-opacity="0.55" vector-effect="non-scaling-stroke"/>'
        )
    for z in geo["zones"]:
        cx, cy = _project(geo, z["lat"], z["lon"])
        r = z["radius_m"] / _radius_per_px(geo)
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="#c0392b" fill-opacity="0.22" '
            f'stroke="#c0392b" stroke-width="1.5" vector-effect="non-scaling-stroke"/>'
            f'<text x="{cx:.1f}" y="{cy - r - 6:.1f}" font-size="11" fill="#c0392b" text-anchor="middle">{e(z["name"])}</text>'
        )
    for item in geo["areas"]:
        cx, cy = _project(geo, item["lat"], item["lon"])
        r = item["radius_m"] / _radius_per_px(geo)
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" stroke="#27ae60" stroke-width="1.5" '
            f'stroke-dasharray="4,3" vector-effect="non-scaling-stroke"/>'
            f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="11" fill="#1e8449" text-anchor="middle">{e(item["name"])}</text>'
        )
    for item in geo["points"]:
        cx, cy = _project(geo, item["lat"], item["lon"])
        r = item["radius_m"] / _radius_per_px(geo)
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{max(r, 3):.1f}" fill="none" stroke="#1e8449" stroke-width="1.2" '
            f'vector-effect="non-scaling-stroke"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.2" fill="#27ae60"/>'
            f'<text x="{cx + 6:.1f}" y="{cy - 6:.1f}" font-size="12" font-weight="600" fill="#1e8449">{e(item["name"])}</text>'
        )
    if geo["home"]:
        hx, hy = _project(geo, geo["home"][0], geo["home"][1])
        parts.append(
            f'<polygon points="{hx:.1f},{hy - 8:.1f} {hx - 7:.1f},{hy + 6:.1f} {hx + 7:.1f},{hy + 6:.1f}" '
            f'fill="#111" stroke="#fff" stroke-width="1"/>'
            f'<text x="{hx:.1f}" y="{hy + 20:.1f}" font-size="11" fill="#111" text-anchor="middle">起飞点</text>'
        )
    if geo["flight"]:
        coords = " ".join(
            f"{_project(geo, la, lo)[0]:.1f},{_project(geo, la, lo)[1]:.1f}"
            for la, lo in geo["flight"]
        )
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="#e67e22" stroke-width="2.8" '
            f'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        )
        fx, fy = _project(geo, geo["flight"][0][0], geo["flight"][0][1])
        parts.append(f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="4" fill="#e67e22"/>')
    return '<svg viewBox="0 0 900 560">' + "".join(parts) + "</svg>"


def _radius_per_px(geo: dict) -> float:
    """Approx metres per SVG pixel in the current bbox (for circle sizing)."""
    lat0, lat1, lon0, lon1 = geo["bbox"]
    mid = math.radians((lat0 + lat1) / 2)
    span_x_m = (lon1 - lon0) * _M_PER_DEG_LAT * math.cos(mid)
    span_y_m = (lat1 - lat0) * _M_PER_DEG_LAT
    return max(span_x_m, span_y_m) / 600.0


def _svg_altitude_profile(flight: FlightLog, task: TaskSpec, e) -> str:
    pts = flight.points
    if not pts:
        return '<svg viewBox="0 0 900 240"></svg>'
    times = [p.time_s for p in pts]
    alts = [p.alt for p in pts]
    t0, t1 = times[0], times[-1]
    alt_min = min(0.0, min(alts) - 5.0)
    alt_max = max(max(alts), task.altitude_range[1]) + 5.0
    span_t = max(t1 - t0, 1e-9)

    def X(t): return (t - t0) / span_t * 900.0
    def Y(a): return (alt_max - a) / (alt_max - alt_min) * 220.0 + 10.0

    lo_y = Y(task.altitude_range[0])
    hi_y = Y(task.altitude_range[1])
    # window band
    band = (
        f'<rect x="0" y="{min(lo_y, hi_y):.1f}" width="900" height="{abs(hi_y - lo_y):.1f}" '
        f'fill="#2ecc71" fill-opacity="0.10"/>'
        f'<line x1="0" y1="{lo_y:.1f}" x2="900" y2="{lo_y:.1f}" stroke="#27ae60" stroke-width="1" stroke-dasharray="4,3"/>'
        f'<line x1="0" y1="{hi_y:.1f}" x2="900" y2="{hi_y:.1f}" stroke="#27ae60" stroke-width="1" stroke-dasharray="4,3"/>'
    )
    path = " ".join(f"{X(t):.1f},{Y(a):.1f}" for t, a in zip(times, alts))
    profile = (
        f'<polyline points="{path}" fill="none" stroke="#e67e22" stroke-width="2.2" '
        f'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
    )
    labels = (
        f'<text x="8" y="18" font-size="11" fill="#27ae60">窗口 {task.altitude_range[0]:.0f}-{task.altitude_range[1]:.0f} m</text>'
        f'<text x="8" y="{(alt_max - min(alts)) / (alt_max - alt_min) * 220 + 24:.0f}" font-size="11" fill="#555">最高 {max(alts):.0f} m</text>'
    )
    return f'<svg viewBox="0 0 900 240">{band}{profile}{labels}</svg>'
