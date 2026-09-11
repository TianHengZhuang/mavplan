"""Mission preview HTML renderer (v1.7 teaching preview).

Single-file, self-contained HTML for classroom projection: plan map
(inline SVG, offline), optional no-fly zones, lawnmower coverage bands,
altitude profile vs cumulative distance, and a tiny click-to-highlight
script. No external tiles, no Leaflet, no runtime dependencies.
"""
from __future__ import annotations

import html
import math
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from .actions import command_name, is_action, NAV_LAND, NAV_RETURN_TO_LAUNCH, NAV_TAKEOFF
from .mission import Mission
from .taskspec import Zone

_M_PER_DEG_LAT = 111_320.0
_W = 900.0
_H = 520.0
_PAD = 36.0
_PROFILE_H = 200.0


def _local_xy(lat: float, lon: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    """East / north metres relative to a reference lat-lon."""
    x = (lon - ref_lon) * _M_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    y = (lat - ref_lat) * _M_PER_DEG_LAT
    return x, y


def _bounds(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lon_min, lon_max) over (lat, lon) pairs."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return min(lats), max(lats), min(lons), max(lons)


def _projector(
    lat_min: float, lat_max: float, lon_min: float, lon_max: float
):
    """Build X(lon)/Y(lat) mapping into the map SVG viewport."""
    mid_lat = math.radians((lat_min + lat_max) / 2.0)
    cos_mid = max(math.cos(mid_lat), 1e-12)
    w_m = max((lon_max - lon_min) * _M_PER_DEG_LAT * cos_mid, 1e-6)
    h_m = max((lat_max - lat_min) * _M_PER_DEG_LAT, 1e-6)
    usable_w = _W - 2 * _PAD
    usable_h = _H - 2 * _PAD - 18.0  # leave a caption strip
    scale = min(usable_w / w_m, usable_h / h_m)
    ox = _PAD + (usable_w - w_m * scale) / 2.0
    oy = _PAD + (usable_h - h_m * scale) / 2.0

    def X(lon: float) -> float:
        return ox + (lon - lon_min) * _M_PER_DEG_LAT * cos_mid * scale

    def Y(lat: float) -> float:
        return oy + (lat_max - lat) * _M_PER_DEG_LAT * scale

    return X, Y, scale, ox, oy, w_m, h_m


def _wp_marker_color(wp) -> str:
    if wp.command == NAV_TAKEOFF:
        return "#27ae60"
    if wp.command == NAV_LAND:
        return "#c0392b"
    if wp.command == NAV_RETURN_TO_LAUNCH:
        return "#8e44ad"
    if is_action(wp.command):
        return "#7f8c8d"
    return "#1a3c6e"


def _svg_map(
    mission: Mission,
    zones: Optional[Sequence[Zone]],
    e,
) -> str:
    wps = [w for w in mission.waypoints() if not is_action(w.command) or w.command in (NAV_TAKEOFF, NAV_LAND)]
    # Include every waypoint with coordinates for bounds; actions inherit coords.
    all_pts = [(w.lat, w.lon) for w in mission.waypoints()]
    if mission.home:
        all_pts.append((mission.home[0], mission.home[1]))
    zone_pts: list[tuple[float, float]] = []
    if zones:
        for z in zones:
            if z.kind == "polygon":
                zone_pts.extend(z.polygon_ring())
            else:
                zone_pts.append((z.lat, z.lon))
                # Expand circle bounds roughly by radius.
                dlat = z.radius_m / _M_PER_DEG_LAT
                dlon = z.radius_m / max(_M_PER_DEG_LAT * math.cos(math.radians(z.lat)), 1e-9)
                zone_pts.append((z.lat + dlat, z.lon + dlon))
                zone_pts.append((z.lat - dlat, z.lon - dlon))
    pts = all_pts + zone_pts
    if not pts:
        return f'<svg viewBox="0 0 {_W:.0f} {_H:.0f}"><text x="20" y="40" font-size="14">无航点</text></svg>'

    lat_min, lat_max, lon_min, lon_max = _bounds(pts)
    # Pad bounds slightly so markers are not clipped.
    lat_pad = max((lat_max - lat_min) * 0.08, 1e-6)
    lon_pad = max((lon_max - lon_min) * 0.08, 1e-6)
    lat_min -= lat_pad
    lat_max += lat_pad
    lon_min -= lon_pad
    lon_max += lon_pad

    X, Y, scale, ox, oy, w_m, h_m = _projector(lat_min, lat_max, lon_min, lon_max)
    parts: list[str] = []

    # Frame
    parts.append(
        f'<rect x="{ox:.1f}" y="{oy:.1f}" width="{w_m * scale:.1f}" height="{h_m * scale:.1f}" '
        f'fill="#f8fafc" stroke="#c5d0e0" stroke-width="1"/>'
    )

    # No-fly zones
    if zones:
        for z in zones:
            if z.kind == "polygon":
                ring = z.polygon_ring()
                if len(ring) >= 3:
                    pts_s = " ".join(f"{X(lon):.1f},{Y(lat):.1f}" for lat, lon in ring)
                    parts.append(
                        f'<polygon points="{pts_s}" fill="#e74c3c" fill-opacity="0.12" '
                        f'stroke="#e74c3c" stroke-width="1.5" stroke-dasharray="4,3"/>'
                    )
                    cx = sum(X(lon) for _, lon in ring) / len(ring)
                    cy = sum(Y(lat) for lat, _ in ring) / len(ring)
                    parts.append(
                        f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="11" fill="#c0392b" '
                        f'text-anchor="middle">{e(z.name)}</text>'
                    )
            else:
                r_px = z.radius_m * scale
                parts.append(
                    f'<circle cx="{X(z.lon):.1f}" cy="{Y(z.lat):.1f}" r="{r_px:.1f}" '
                    f'fill="#e74c3c" fill-opacity="0.12" stroke="#e74c3c" stroke-width="1.5" '
                    f'stroke-dasharray="4,3"/>'
                )
                parts.append(
                    f'<text x="{X(z.lon):.1f}" y="{Y(z.lat):.1f}" font-size="11" fill="#c0392b" '
                    f'text-anchor="middle">{e(z.name)}</text>'
                )

    # Coverage bands (lawnmower EW rows)
    try:
        from .survey import extract_ew_rows

        rows = extract_ew_rows(mission)
        half_m = 12.0  # visual half-width when footprint unknown
        for r in rows:
            y = Y(r["lat"])
            half_px = half_m * scale
            parts.append(
                f'<rect x="{X(r["lon_a"]):.1f}" y="{y - half_px:.1f}" '
                f'width="{abs(X(r["lon_b"]) - X(r["lon_a"])):.1f}" height="{2 * half_px:.1f}" '
                f'fill="#3498db" fill-opacity="0.14"/>'
            )
    except Exception:
        rows = []

    # Home
    if mission.home:
        hx, hy = X(mission.home[1]), Y(mission.home[0])
        parts.append(
            f'<g class="wp" data-seq="HOME">'
            f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="6" fill="#f39c12" stroke="#fff" stroke-width="1.5"/>'
            f'<text x="{hx:.1f}" y="{hy + 18:.1f}" font-size="11" text-anchor="middle" fill="#b9770e">HOME</text>'
            f"</g>"
        )

    # Route polyline (nav path)
    nav_path = [w for w in mission.waypoints() if not is_action(w.command)]
    if len(nav_path) >= 2:
        coords = " ".join(f"{X(w.lon):.1f},{Y(w.lat):.1f}" for w in nav_path)
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="#1a3c6e" stroke-width="2.2" '
            f'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        )
        # Heading arrows at mid of each leg
        for a, b in zip(nav_path, nav_path[1:]):
            mx = (X(a.lon) + X(b.lon)) / 2.0
            my = (Y(a.lat) + Y(b.lat)) / 2.0
            dx = X(b.lon) - X(a.lon)
            dy = Y(b.lat) - Y(a.lat)
            if abs(dx) < 0.5 and abs(dy) < 0.5:
                continue
            ang = math.degrees(math.atan2(dy, dx))
            parts.append(
                f'<g transform="translate({mx:.1f},{my:.1f}) rotate({ang:.1f})">'
                f'<polygon points="0,0 -7,-4 -7,4" fill="#1a3c6e" opacity="0.75"/></g>'
            )

    # Waypoint markers
    for w in mission.waypoints():
        cx, cy = X(w.lon), Y(w.lat)
        color = _wp_marker_color(w)
        label = str(w.seq)
        title = f"WP{w.seq} {command_name(w.command)} {w.lat:.6f},{w.lon:.6f} alt={w.alt:.0f}m"
        if is_action(w.command) and w.command not in (NAV_TAKEOFF, NAV_LAND):
            parts.append(
                f'<g class="wp" data-seq="{w.seq}" data-alt="{w.alt:.1f}" data-cmd="{e(command_name(w.command))}" '
                f'data-lat="{w.lat:.6f}" data-lon="{w.lon:.6f}">'
                f'<rect x="{cx - 5:.1f}" y="{cy - 5:.1f}" width="10" height="10" fill="{color}" '
                f'stroke="#fff" stroke-width="1"><title>{e(title)}</title></rect>'
                f"</g>"
            )
            continue
        parts.append(
            f'<g class="wp" data-seq="{w.seq}" data-alt="{w.alt:.1f}" data-cmd="{e(command_name(w.command))}" '
            f'data-lat="{w.lat:.6f}" data-lon="{w.lon:.6f}">'
            f'<circle class="wp-dot" cx="{cx:.1f}" cy="{cy:.1f}" r="7" fill="{color}" '
            f'stroke="#fff" stroke-width="1.5"><title>{e(title)}</title></circle>'
            f'<text x="{cx:.1f}" y="{cy + 3.5:.1f}" font-size="9" fill="#fff" text-anchor="middle" '
            f'font-weight="700" pointer-events="none">{e(label)}</text>'
            f"</g>"
        )

    caption = (
        f'<text x="{ox:.0f}" y="{oy + h_m * scale + 22:.0f}" font-size="12" fill="#555">'
        f"比例约 {scale:.4f} px/m · 离线矢量图 · 禁飞区红虚线 · 覆盖带浅蓝</text>"
    )
    parts.append(caption)
    return f'<svg id="map" viewBox="0 0 {_W:.0f} {_H:.0f}" xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'


def _svg_profile(mission: Mission, e) -> str:
    wps = [w for w in mission.waypoints() if not is_action(w.command)]
    if len(wps) < 2:
        return (
            f'<svg id="profile" viewBox="0 0 900 {_PROFILE_H + 20:.0f}">'
            f'<text x="12" y="20" font-size="12" fill="#777">航点不足，无法绘制高度剖面</text></svg>'
        )

    dists = [0.0]
    for a, b in zip(wps, wps[1:]):
        dists.append(dists[-1] + a.distance_to(b))
    alts = [w.alt for w in wps]
    d0, d1 = dists[0], dists[-1]
    alt_min = min(0.0, min(alts) - 5.0)
    alt_max = max(max(alts) + 10.0, 20.0)
    span = max(d1 - d0, 1e-9)

    def X(d: float) -> float:
        return 50.0 + (d - d0) / span * 820.0

    def Y(a: float) -> float:
        return 12.0 + (alt_max - a) / (alt_max - alt_min) * (_PROFILE_H - 30.0)

    path = " ".join(f"{X(d):.1f},{Y(a):.1f}" for d, a in zip(dists, alts))
    parts = [
        f'<line x1="50" y1="{Y(0):.1f}" x2="870" y2="{Y(0):.1f}" stroke="#dde3ec" stroke-width="1"/>',
        f'<polyline points="{path}" fill="none" stroke="#e67e22" stroke-width="2.2" '
        f'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>',
        f'<text x="8" y="18" font-size="11" fill="#889">高度剖面（横轴=累计距离 m）</text>',
        f'<text x="870" y="18" font-size="11" fill="#889" text-anchor="end">最高 {max(alts):.0f} m · 全程 {d1:.0f} m</text>',
    ]
    for w, d in zip(wps, dists):
        cx, cy = X(d), Y(w.alt)
        color = _wp_marker_color(w)
        parts.append(
            f'<g class="wp" data-seq="{w.seq}" data-alt="{w.alt:.1f}" data-cmd="{e(command_name(w.command))}" '
            f'data-lat="{w.lat:.6f}" data-lon="{w.lon:.6f}">'
            f'<circle class="wp-dot" cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="{color}" stroke="#fff" stroke-width="1.2"/>'
            f'<text x="{cx:.1f}" y="{cy - 8:.1f}" font-size="9" fill="#555" text-anchor="middle">{w.seq}</text>'
            f"</g>"
        )
    return f'<svg id="profile" viewBox="0 0 900 {_PROFILE_H + 20:.0f}" xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'


def _table_rows(mission: Mission) -> str:
    rows = []
    for w in mission.waypoints():
        kind = "动作" if is_action(w.command) else "导航"
        rows.append(
            f"<tr data-seq=\"{w.seq}\" class=\"wp-row\">"
            f"<td>{w.seq}</td>"
            f"<td>{html.escape(command_name(w.command))}</td>"
            f"<td>{kind}</td>"
            f"<td class=\"num\">{w.lat:.6f}</td>"
            f"<td class=\"num\">{w.lon:.6f}</td>"
            f"<td class=\"num\">{w.alt:.0f}</td>"
            f"<td class=\"num\">{w.speed:.1f}</td>"
            f"</tr>"
        )
    return "".join(rows)


def render_mission_preview(
    mission: Mission,
    *,
    zones: Optional[Sequence[Zone]] = None,
    title: str = "",
    output_path: str = "",
) -> str:
    """Render a self-contained mission preview HTML document.

    Args:
        mission: Planned mission.
        zones: Optional no-fly zones to overlay.
        title: Page title override (defaults to mission name).
        output_path: When set, write the HTML to this path.

    Returns:
        The complete HTML document as text.
    """
    e = html.escape
    nav_count = sum(1 for w in mission.waypoints() if not is_action(w.command))
    act_count = len(mission) - nav_count
    dist_m = mission.total_distance()
    dur_s = mission.estimated_duration()
    alts = [w.alt for w in mission.waypoints()] or [0.0]
    mins, secs = divmod(int(dur_s), 60)
    page_title = title or mission.name or "任务预览"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    zone_note = "、".join(e(z.name) for z in zones) if zones else "无"

    cards = "".join(
        f'<div class="metric"><div class="metric-label">{lab}</div>'
        f'<div class="metric-value">{val}</div><div class="metric-sub">{sub}</div></div>'
        for lab, val, sub in [
            ("航点", f"{nav_count}", f"动作 {act_count}"),
            ("航程", f"{dist_m / 1000:.2f} km", f"{dist_m:.0f} m"),
            ("预估时长", f"{mins}分{secs:02d}秒", "按 10 m/s"),
            ("最高高度", f"{max(alts):.0f} m", f"最低 {min(alts):.0f} m"),
        ]
    )

    home_str = (
        f"{mission.home[0]:.6f}, {mission.home[1]:.6f}（{mission.home[2]:.0f} m）"
        if mission.home
        else "未设置"
    )

    script = """
document.querySelectorAll('g.wp').forEach(function (g) {
  g.style.cursor = 'pointer';
  g.addEventListener('click', function () {
    var seq = g.getAttribute('data-seq');
    document.querySelectorAll('g.wp').forEach(function (x) {
      x.classList.toggle('active', x.getAttribute('data-seq') === seq);
    });
    document.querySelectorAll('tr.wp-row').forEach(function (r) {
      var on = r.getAttribute('data-seq') === seq;
      r.classList.toggle('active', on);
      if (on) { r.scrollIntoView({block: 'nearest'}); }
    });
    var info = document.getElementById('wp-info');
    if (info) {
      info.textContent = '选中 WP' + seq + ' · ' + (g.getAttribute('data-cmd') || '') +
        ' · 高度 ' + (g.getAttribute('data-alt') || '') + ' m · ' +
        (g.getAttribute('data-lat') || '') + ', ' + (g.getAttribute('data-lon') || '');
    }
  });
});
"""

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>任务预览 · {e(page_title)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f2f4f8; color: #222; padding: 24px; }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  .page {{ background: #fff; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.08); padding: 28px 32px; }}
  h1 {{ font-size: 22px; color: #1a3c6e; margin-bottom: 4px; }}
  h2 {{ font-size: 15px; color: #555; font-weight: 400; margin: 4px 0 16px; }}
  h3 {{ font-size: 15px; color: #1a3c6e; margin: 24px 0 10px; border-left: 4px solid #1a3c6e; padding-left: 8px; }}
  .sub {{ color: #777; font-size: 12px; margin-bottom: 16px; }}
  .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 14px 0 18px; }}
  .metric {{ background: #f7f9fc; border: 1px solid #e3e8f0; border-radius: 8px; padding: 12px; text-align: center; }}
  .metric-label {{ font-size: 12px; color: #667; }}
  .metric-value {{ font-size: 20px; font-weight: 700; color: #1a3c6e; }}
  .metric-sub {{ font-size: 11px; color: #889; margin-top: 4px; }}
  svg {{ width: 100%; height: auto; border: 1px solid #e3e8f0; border-radius: 8px; background: #fbfcfe; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; }}
  th, td {{ border: 1px solid #dde3ec; padding: 6px 8px; text-align: left; }}
  th {{ background: #f0f4fa; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr.wp-row.active {{ background: #fff3cd; }}
  g.wp.active .wp-dot {{ stroke: #f39c12; stroke-width: 3; }}
  #wp-info {{ font-size: 13px; color: #1a3c6e; background: #eef4ff; border-radius: 6px; padding: 8px 12px; margin: 10px 0; min-height: 36px; }}
  .meta th {{ width: 120px; }}
  .footer {{ text-align: center; color: #99a; font-size: 12px; margin-top: 22px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="page">
    <h1>任务规划预览</h1>
    <h2>{e(page_title)}</h2>
    <div class="sub">生成时间：{e(now)} · mavplan v1.7 教学预览 · 完全离线</div>
    <div class="metrics">{cards}</div>
    <div id="wp-info">点击地图或剖面上的航点查看详情。</div>

    <h3>任务概要</h3>
    <table class="meta"><tbody>
      <tr><th>任务名称</th><td>{e(mission.name)}</td></tr>
      <tr><th>坐标系</th><td>frame={mission.frame}</td></tr>
      <tr><th>Home</th><td>{e(home_str)}</td></tr>
      <tr><th>禁飞区</th><td>{zone_note}</td></tr>
      <tr><th>航点总数</th><td>{len(mission)}（导航 {nav_count} / 动作 {act_count}）</td></tr>
    </tbody></table>

    <h3>航线地图（离线 SVG）</h3>
    {_svg_map(mission, zones, e)}

    <h3>高度剖面</h3>
    {_svg_profile(mission, e)}

    <h3>航点明细</h3>
    <table>
      <thead><tr><th>序号</th><th>指令</th><th>类型</th><th>纬度</th><th>经度</th><th>高度 m</th><th>速度 m/s</th></tr></thead>
      <tbody>{_table_rows(mission)}</tbody>
    </table>

    <div class="footer">本页面由 mavplan 生成，用于航线规划教学投屏；断网可用。</div>
  </div>
</div>
<script>
{script}
</script>
</body>
</html>
"""
    if output_path:
        Path(output_path).write_text(html_doc, encoding="utf-8")
    return html_doc
