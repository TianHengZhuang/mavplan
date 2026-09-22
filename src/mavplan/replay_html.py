"""Flight replay HTML renderer (v1.13 ``analyze replay``).

Single-file, self-contained offline HTML for classroom replay:

  * planned route vs actual flight track on an inline SVG map
  * timeline scrubber plus play / pause / reset and 1x / 2x / 4x rate
  * live altitude, speed, heading and elapsed-time gauges
  * altitude-vs-distance profile with a moving cursor

Everything is inline SVG plus vanilla JS: no map tiles, no JS libraries,
no runtime dependencies, so the page keeps working with the network
unplugged (roadmap v1.2 acceptance: offline usable, adjustable replay
frame rate, output below 2 MB).
"""
from __future__ import annotations

import html
import math
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from .flightlog import FlightLog, compare_to_plan
from .mission import Mission

_M_PER_DEG_LAT = 111_320.0
_W = 900.0
_H = 460.0
_PAD = 32.0
_PROFILE_W = 900.0
_PROFILE_H = 170.0
_PAD_P = 32.0
_MIN_FPS = 1
_MAX_FPS = 60
_MAX_SAMPLES = 1200

_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f2f4f8; color: #222; padding: 24px; }
  .wrap { max-width: 980px; margin: 0 auto; }
  .page { background: #fff; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.08); padding: 28px 32px; }
  h1 { font-size: 22px; color: #1a3c6e; margin-bottom: 4px; }
  h2 { font-size: 15px; color: #555; font-weight: 400; margin: 4px 0 16px; }
  h3 { font-size: 15px; color: #1a3c6e; margin: 24px 0 10px; border-left: 4px solid #1a3c6e; padding-left: 8px; }
  .sub { color: #777; font-size: 12px; margin-bottom: 16px; }
  .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 14px 0 18px; }
  .metric { background: #f7f9fc; border: 1px solid #e3e8f0; border-radius: 8px; padding: 12px; text-align: center; }
  .metric-label { font-size: 12px; color: #667; }
  .metric-value { font-size: 20px; font-weight: 700; color: #1a3c6e; }
  .metric-sub { font-size: 11px; color: #889; margin-top: 4px; }
  svg { width: 100%; height: auto; border: 1px solid #e3e8f0; border-radius: 8px; background: #fbfcfe; }
  .controls { display: flex; align-items: center; gap: 12px; margin: 12px 0 4px; flex-wrap: wrap; }
  button { font: inherit; font-size: 13px; padding: 6px 14px; border-radius: 6px; border: 1px solid #1a3c6e; background: #1a3c6e; color: #fff; cursor: pointer; }
  button.ghost { background: #fff; color: #1a3c6e; }
  input[type=range] { flex: 1 1 260px; min-width: 200px; }
  select { font: inherit; font-size: 13px; padding: 5px 8px; border-radius: 6px; border: 1px solid #cfd8e6; background: #fff; }
  .clock { font-variant-numeric: tabular-nums; font-size: 13px; color: #1a3c6e; min-width: 96px; text-align: right; }
  .gauges { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 12px 0 4px; }
  .gauge { background: #f7f9fc; border: 1px solid #e3e8f0; border-radius: 8px; padding: 10px 12px; }
  .gauge-label { font-size: 12px; color: #667; }
  .gauge-value { font-size: 18px; font-weight: 700; color: #1a3c6e; font-variant-numeric: tabular-nums; }
  .bar { height: 6px; border-radius: 3px; background: #e3e8f0; margin-top: 6px; overflow: hidden; }
  .bar > i { display: block; height: 100%; width: 0; background: #3b7ddd; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; }
  th, td { border: 1px solid #dde3ec; padding: 6px 8px; text-align: left; }
  th { background: #f0f4fa; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .legend { font-size: 12px; color: #556; margin-top: 8px; }
  .footer { text-align: center; color: #99a; font-size: 12px; margin-top: 22px; }
"""

_JS = """
(function () {
  var TRK = __TRK__;
  var N = TRK.length;
  var FPS = __FPS__;
  var PW = __PW__, PPAD = __PPAD__, DMAX = __DMAX__;
  var MAXALT = __MAXALT__, MAXSPD = __MAXSPD__;
  var idx = 0, timer = null, rate = 1;

  var mk = document.getElementById('marker');
  var tl = document.getElementById('tl');
  var pg = document.getElementById('pcursor');
  var clock = document.getElementById('clock');
  var gAlt = document.getElementById('g-alt');
  var gSpd = document.getElementById('g-spd');
  var gHdg = document.getElementById('g-hdg');
  var gT = document.getElementById('g-t');
  var bAlt = document.getElementById('bar-alt');
  var bSpd = document.getElementById('bar-spd');
  var btn = document.getElementById('play');

  function pad2(n) { return n < 10 ? '0' + n : '' + n; }
  function fmt(s) {
    if (!isFinite(s) || s < 0) { s = 0; }
    return pad2(Math.floor(s / 60)) + ':' + pad2(Math.floor(s % 60));
  }
  function place(i) {
    idx = Math.max(0, Math.min(N - 1, i));
    var p = TRK[idx];
    mk.setAttribute('transform', 'translate(' + p[0] + ',' + p[1] + ')');
    tl.value = idx;
    var x = PPAD + (p[2] / DMAX) * (PW - 2 * PPAD);
    pg.setAttribute('x1', x);
    pg.setAttribute('x2', x);
    gAlt.textContent = p[4].toFixed(1);
    gSpd.textContent = p[5].toFixed(1);
    gHdg.textContent = p[6].toFixed(0);
    gT.textContent = fmt(p[3]);
    bAlt.style.width = Math.min(100, (p[4] / MAXALT) * 100) + '%';
    bSpd.style.width = Math.min(100, (p[5] / MAXSPD) * 100) + '%';
    clock.textContent = fmt(p[3]) + ' / ' + fmt(TRK[N - 1][3]);
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    btn.textContent = '播放';
  }
  function start() {
    if (timer) { return; }
    if (idx >= N - 1) { place(0); }
    btn.textContent = '暂停';
    timer = setInterval(function () {
      if (idx >= N - 1) { stop(); return; }
      place(idx + 1);
    }, 1000 / (FPS * rate));
  }
  btn.addEventListener('click', function () { if (timer) { stop(); } else { start(); } });
  document.getElementById('reset').addEventListener('click', function () { stop(); place(0); });
  document.getElementById('rate').addEventListener('change', function (ev) {
    rate = parseFloat(ev.target.value) || 1;
    if (timer) { stop(); start(); }
  });
  tl.addEventListener('input', function (ev) {
    stop();
    place(parseInt(ev.target.value, 10) || 0);
  });
  place(0);
})();
"""


def _bounds(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lon_min, lon_max) with degenerate spans padded."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    if lat_max - lat_min < 1e-7:
        lat_min -= 5e-6
        lat_max += 5e-6
    if lon_max - lon_min < 1e-7:
        lon_min -= 5e-6
        lon_max += 5e-6
    return lat_min, lat_max, lon_min, lon_max


def _projector(
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    width: float,
    height: float,
    pad: float,
):
    """Build X(lon) / Y(lat) mappings into a ``width`` x ``height`` viewport."""
    mid_lat = math.radians((lat_min + lat_max) / 2.0)
    cos_mid = max(math.cos(mid_lat), 1e-12)
    w_m = max((lon_max - lon_min) * _M_PER_DEG_LAT * cos_mid, 1e-6)
    h_m = max((lat_max - lat_min) * _M_PER_DEG_LAT, 1e-6)
    usable_w = width - 2 * pad
    usable_h = height - 2 * pad
    scale = min(usable_w / w_m, usable_h / h_m)
    ox = pad + (usable_w - w_m * scale) / 2.0
    oy = pad + (usable_h - h_m * scale) / 2.0

    def X(lon: float) -> float:
        return ox + (lon - lon_min) * _M_PER_DEG_LAT * cos_mid * scale

    def Y(lat: float) -> float:
        return oy + (lat_max - lat) * _M_PER_DEG_LAT * scale

    return X, Y


def _sample_indices(n: int, limit: int) -> list[int]:
    """Evenly spaced indices (always keeping the first and the last point)."""
    if n <= limit:
        return list(range(n))
    step = (n - 1) / float(limit - 1)
    out = sorted({int(round(i * step)) for i in range(limit)})
    if out and out[-1] != n - 1:
        out[-1] = n - 1
    return out


def _fmt_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds >= 3600:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m {int(seconds % 60)}s"
    if seconds >= 60:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    return f"{seconds:.1f}s"


def render_replay_html(
    flight: FlightLog,
    plan: Optional[Mission] = None,
    *,
    title: str = "",
    output_path: str = "",
    fps: int = 10,
    max_frames: int = _MAX_SAMPLES,
) -> str:
    """Render a self-contained flight replay HTML document.

    Args:
        flight: Parsed flight log with telemetry samples.
        plan: Optional planned mission to overlay as a reference route.
        title: Page title override.
        output_path: When set, write the HTML to this path.
        fps: Replay frame rate (1-60); the page offers 1x / 2x / 4x on top.
        max_frames: Upper bound on embedded replay samples (down-sampled).

    Returns:
        The complete HTML document as text.

    Raises:
        ValueError: On an empty flight log or an out-of-range ``fps``.
    """
    if fps < _MIN_FPS or fps > _MAX_FPS:
        raise ValueError(f"fps must be between {_MIN_FPS} and {_MAX_FPS}")
    if not flight.points:
        raise ValueError("Flight log has no points to replay")

    limit = max(2, int(max_frames))
    e = html.escape

    samples = [flight.points[i] for i in _sample_indices(len(flight.points), limit)]

    cum = [0.0]
    for a, b in zip(samples, samples[1:]):
        cum.append(cum[-1] + a.distance_to(b))
    flight_dist = cum[-1]

    plan_wps = list(plan.waypoints()) if plan is not None else []
    plan_cum = [0.0]
    for a, b in zip(plan_wps, plan_wps[1:]):
        plan_cum.append(plan_cum[-1] + a.distance_to(b))
    plan_dist = plan_cum[-1] if plan_cum else 0.0

    latlon = [(p.lat, p.lon) for p in samples] + [(w.lat, w.lon) for w in plan_wps]
    X, Y = _projector(*_bounds(latlon), _W, _H, _PAD)

    trk = [
        [round(X(p.lon), 1), round(Y(p.lat), 1), round(d, 1), round(p.time_s, 2),
         round(p.alt, 2), round(p.speed, 2), round(p.heading, 1)]
        for p, d in zip(samples, cum)
    ]
    trk_line = " ".join(f"{row[0]},{row[1]}" for row in trk)
    plan_line = " ".join(
        f"{X(w.lon):.1f},{Y(w.lat):.1f}" for w in plan_wps
    )

    alts = [p.alt for p in samples] + [w.alt for w in plan_wps]
    alt_min = min(alts)
    alt_max = max(alts)
    if alt_max - alt_min < 1.0:
        alt_max = alt_min + 1.0
    dist_max = max(flight_dist, plan_dist, 1.0)

    def px(d: float) -> float:
        return _PAD_P + (d / dist_max) * (_PROFILE_W - 2 * _PAD_P)

    def py(a: float) -> float:
        span = alt_max - alt_min
        return _PROFILE_H - _PAD_P - ((a - alt_min) / span) * (_PROFILE_H - 2 * _PAD_P)

    prof_line = " ".join(f"{px(d):.1f},{py(p.alt):.1f}" for p, d in zip(samples, cum))
    plan_prof = " ".join(f"{px(d):.1f},{py(w.alt):.1f}" for w, d in zip(plan_wps, plan_cum))

    span = alt_max - alt_min
    y0 = py(alt_min)
    y1 = py(alt_max)
    alt_axis = ""
    for k in range(5):
        a = alt_min + span * k / 4.0
        yy = py(a)
        alt_axis += (
            f'<line x1="{_PAD_P:.1f}" y1="{yy:.1f}" x2="{_PROFILE_W - _PAD_P:.1f}" '
            f'y2="{yy:.1f}" stroke="#e8edf5" stroke-width="1"/>'
            f'<text x="{_PAD_P - 6:.1f}" y="{yy + 3:.1f}" text-anchor="end" '
            f'font-size="10" fill="#889">{a:.0f}</text>'
        )
    alt_axis += (
        f'<text x="{_PAD_P - 6:.1f}" y="{y1 - 4:.1f}" text-anchor="end" font-size="10" fill="#889">m</text>'
    )

    stats = flight.stats()
    page_title = (
        title
        or (plan.name if plan is not None and plan.name else "")
        or (Path(flight.source_file).stem if flight.source_file else "")
        or "飞行回放"
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    compare_rows = ""
    coverage_txt = "—"
    if plan is not None and plan_wps:
        cmp = compare_to_plan(flight, plan)
        if "error" not in cmp:
            coverage_txt = f"{cmp['coverage_ratio']:.0%}"
            compare_rows = (
                f'<tr><th>计划里程</th><td class="num">{cmp["plan_distance_m"] / 1000:.2f} km</td>'
                f'<th>实际里程</th><td class="num">{cmp["flight_distance_m"] / 1000:.2f} km</td></tr>'
                f'<tr><th>航线覆盖率</th><td class="num">{cmp["coverage_ratio"]:.0%}</td>'
                f'<th>平均高度偏差</th><td class="num">{cmp["avg_altitude_error_m"]:.1f} m</td></tr>'
                f'<tr><th>命中率 ≤10 m</th><td class="num">{cmp["waypoint_hits_10m"]}/{cmp["total_plan_waypoints"]}</td>'
                f'<th>命中率 ≤50 m</th><td class="num">{cmp["waypoint_hits_50m"]}/{cmp["total_plan_waypoints"]}</td></tr>'
            )

    cards = "".join(
        f'<div class="metric"><div class="metric-label">{lab}</div>'
        f'<div class="metric-value">{val}</div><div class="metric-sub">{sub}</div></div>'
        for lab, val, sub in [
            ("日志点数", f"{stats.num_points}", f"回放采样 {len(trk)}"),
            ("飞行时长", _fmt_duration(stats.flight_duration_s), "日志时间跨度"),
            ("飞行里程", f"{stats.total_distance_m / 1000:.2f} km", f"直线 {stats.horizontal_distance_m / 1000:.2f} km"),
            ("航线覆盖率", coverage_txt, "对计划航线" if plan is not None else "未提供计划"),
        ]
    )

    compare_block = ""
    if compare_rows:
        compare_block = (
            '<h3>计划对比</h3><table><tbody>' + compare_rows + "</tbody></table>"
        )

    legend = (
        '<div class="legend"><b>图例</b>：绿色虚线 = 计划航线（'
        f'{len(plan_wps)} 点）；蓝色实线 = 实际轨迹；红色圆点 = 当前回放位置。</div>'
        if plan_wps
        else '<div class="legend"><b>图例</b>：蓝色实线 = 实际轨迹；红色圆点 = 当前回放位置。</div>'
    )

    js = (
        _JS.replace("__TRK__", _json_numbers(trk))
        .replace("__FPS__", str(int(fps)))
        .replace("__PW__", f"{_PROFILE_W:.1f}")
        .replace("__PPAD__", f"{_PAD_P:.1f}")
        .replace("__DMAX__", f"{dist_max:.1f}")
        .replace("__MAXALT__", f"{max(alt_max, 1.0):.1f}")
        .replace("__MAXSPD__", f"{max(stats.max_speed_mps, 1.0):.1f}")
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>飞行回放 · {e(page_title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="page">
    <h1>飞行回放</h1>
    <h2>{e(page_title)}</h2>
    <div class="sub">生成时间：{e(now)} · mavplan 飞行回放（analyze replay）· 完全离线单文件</div>
    <div class="metrics">{cards}</div>

    <h3>航线地图（计划 vs 实际）</h3>
    <svg id="map" viewBox="0 0 {_W:.0f} {_H:.0f}" role="img" aria-label="飞行轨迹与计划航线对比图">
      <polyline class="plan-line" points="{plan_line}" fill="none" stroke="#2e9e5b" stroke-width="2" stroke-dasharray="7 5" stroke-linejoin="round"/>
      <polyline class="trk-line" points="{trk_line}" fill="none" stroke="#2b6cb0" stroke-width="2.2" stroke-linejoin="round"/>
      <g id="marker" transform="translate(-99,-99)">
        <circle r="9" fill="#e74c3c" opacity="0.18"/>
        <circle r="4.5" fill="#e74c3c" stroke="#fff" stroke-width="1.5"/>
      </g>
    </svg>
    {legend}

    <div class="controls">
      <button id="play" type="button">播放</button>
      <button id="reset" type="button" class="ghost">重置</button>
      <input id="tl" type="range" min="0" max="{len(trk) - 1}" value="0" step="1" aria-label="回放时间轴">
      <span id="clock" class="clock">00:00 / 00:00</span>
      <select id="rate" aria-label="回放倍速">
        <option value="1">1x</option>
        <option value="2">2x</option>
        <option value="4">4x</option>
      </select>
    </div>

    <div class="gauges">
      <div class="gauge"><div class="gauge-label">高度 m</div><div class="gauge-value" id="g-alt">0.0</div><div class="bar"><i id="bar-alt"></i></div></div>
      <div class="gauge"><div class="gauge-label">速度 m/s</div><div class="gauge-value" id="g-spd">0.0</div><div class="bar"><i id="bar-spd"></i></div></div>
      <div class="gauge"><div class="gauge-label">航向 °</div><div class="gauge-value" id="g-hdg">0</div></div>
      <div class="gauge"><div class="gauge-label">已飞时间</div><div class="gauge-value" id="g-t">00:00</div></div>
    </div>

    <h3>高度剖面（高度 vs 累计距离）</h3>
    <svg id="profile" viewBox="0 0 {_PROFILE_W:.0f} {_PROFILE_H:.0f}" role="img" aria-label="高度剖面">
      {alt_axis}
      <polyline points="{plan_prof}" fill="none" stroke="#2e9e5b" stroke-width="1.6" stroke-dasharray="6 4"/>
      <polyline points="{prof_line}" fill="none" stroke="#2b6cb0" stroke-width="2"/>
      <line id="pcursor" x1="{_PAD_P:.1f}" y1="{_PAD_P:.1f}" x2="{_PAD_P:.1f}" y2="{_PROFILE_H - _PAD_P:.1f}" stroke="#e74c3c" stroke-width="1.5"/>
    </svg>

    {compare_block}

    <div class="footer">本页面由 mavplan 生成，用于飞行回放教学投屏；断网可用，可直接归档留证。</div>
  </div>
</div>
<script>
{js}
</script>
</body>
</html>
"""
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(html_doc, encoding="utf-8")
    return html_doc


def _json_numbers(rows: Sequence[Sequence[float]]) -> str:
    """Compact JS array literal for the embedded telemetry frames."""
    return "[" + ",".join("[" + ",".join(f"{v:g}" for v in row) + "]" for row in rows) + "]"
