"""Mission file format interop: QGC WPL text and QGroundControl .plan JSON.

Supported formats (auto-detected by :func:`sniff_format`):

- ``mavplan`` — native JSON (Mission.save / Mission.load)
- ``wpl``     — QGC WPL 110/120 text (QGroundControl / Mission Planner .waypoints)
- ``qgcplan`` — QGroundControl ``.plan`` JSON (fileType "Plan")
"""
from __future__ import annotations

import json
from pathlib import Path

from .mission import Mission
from .waypoint import Waypoint

WPL_HEADERS = ("QGC WPL 110", "QGC WPL 120")


def _read_text(source: str | Path) -> str:
    """Read a mission file, tolerating a UTF-8 BOM (PowerShell ``utf8`` default)."""
    if isinstance(source, (str, Path)) and Path(source).exists():
        return Path(source).read_text(encoding="utf-8-sig", errors="replace")
    return str(source).lstrip("﻿")


def sniff_format(source: str | Path) -> str | None:
    """Detect mission file format from a path or raw text.

    Returns ``"mavplan"``, ``"wpl"``, ``"qgcplan"`` or None when unrecognised.
    """
    text = _read_text(source)
    stripped = text.lstrip()
    if stripped.startswith(WPL_HEADERS):
        return "wpl"
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if data.get("fileType") == "Plan":
            return "qgcplan"
        if "waypoints" in data or "name" in data:
            return "mavplan"
    return None


def load_mission_file(path: str | Path) -> Mission:
    """Load a mission from any supported format (auto-detected)."""
    fmt = sniff_format(path)
    if fmt is None:
        raise ValueError(f"Cannot detect mission format: {path}")
    text = _read_text(path)
    if fmt == "mavplan":
        return Mission.load(path)
    if fmt == "wpl":
        return parse_wpl(text)
    return parse_qgc_plan(text)


# ---------------------------------------------------------------------------
# QGC WPL text (Mission Planner / QGroundControl .waypoints)
# ---------------------------------------------------------------------------

def parse_wpl(text: str) -> Mission:
    """Parse a ``QGC WPL 110/120`` mission file into a Mission.

    A leading HOME item (command NAV_WAYPOINT in MAV_FRAME_GLOBAL) becomes
    ``mission.home``.  All remaining items — including DO_* action items —
    are preserved verbatim as waypoints.
    """
    text = text.lstrip("﻿")
    mission = Mission(name="Imported Mission")
    seen_header = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("QGC WPL"):
            if line.startswith("QGC WPL"):
                seen_header = True
            continue
        parts = line.replace(",", "\t").split("\t")
        parts = [p for p in parts if p != ""]
        if len(parts) < 11:
            continue  # malformed row
        seq = int(float(parts[0]))
        frame = int(float(parts[2]))
        command = int(float(parts[3]))
        p1 = float(parts[4])
        p2 = float(parts[5])
        p3 = float(parts[6])
        p4 = float(parts[7])
        x = float(parts[8])
        y = float(parts[9])
        z = float(parts[10])
        autocontinue = int(float(parts[11])) if len(parts) > 11 else 1

        # HOME item: NAV_WAYPOINT in MAV_FRAME_GLOBAL (frame 0), usually seq 0
        if command == 16 and frame == 0 and mission.home is None:
            mission.home = (x, y, z)
            continue

        wp = Waypoint(
            lat=x,
            lon=y,
            alt=z,
            delay=p1,
            acceptance_radius=p2,
            orbit=p3,
            yaw=p4,
            command=command,
            frame=frame,
            autocontinue=autocontinue,
        )
        wp.seq = len(mission._waypoints)
        mission._waypoints.append(wp)
    if not seen_header:
        raise ValueError("Not a QGC WPL mission file (missing 'QGC WPL' header)")
    return mission


def to_wpl(mission: Mission, header: str = "QGC WPL 110") -> str:
    """Serialize a Mission to QGC WPL text (QGroundControl/Mission Planner).

    The home position (``mission.home`` if set) is emitted as a leading
    MAV_FRAME_GLOBAL NAV_WAYPOINT item.
    """
    lines = [header]
    seq = 0
    if mission.home is not None:
        lat, lon, alt = mission.home
        vals = [seq, 0, 0, 16, 1, 0, 0, 0, round(float(lat), 7), round(float(lon), 7), round(float(alt), 2)]
        lines.append("\t".join(str(v) for v in vals))
        seq += 1
    for wp in mission._waypoints:
        item = wp.to_mavlink_item()
        vals = [
            seq,
            item["current"],
            item["frame"],
            item["command"],
            round(item["param1"], 4),
            round(item["param2"], 4),
            round(item["param3"], 4),
            round(item["param4"], 4),
            round(item["x"], 7),
            round(item["y"], 7),
            round(item["z"], 2),
        ]
        lines.append("\t".join(str(v) for v in vals))
        seq += 1
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# QGroundControl .plan JSON
# ---------------------------------------------------------------------------

def parse_qgc_plan(text: str) -> Mission:
    """Parse a QGroundControl ``.plan`` JSON document into a Mission.

    ``mission.plannedHomePosition`` becomes ``mission.home``; every entry in
    ``mission.items`` is mapped to a waypoint (NAV_* and DO_* alike) using the
    authoritative 7-element ``params`` array [p1..p4, x, y, z].  Geo-fence and
    rally-point sections are ignored (round-trip note: not preserved).
    """
    data = json.loads(text)
    if data.get("fileType") != "Plan":
        raise ValueError("Not a QGroundControl .plan file (missing fileType 'Plan')")
    mission = Mission(name="Imported Plan")
    planned_home = (data.get("mission") or {}).get("plannedHomePosition")
    if isinstance(planned_home, list) and len(planned_home) >= 3:
        mission.home = (float(planned_home[0]), float(planned_home[1]), float(planned_home[2]))

    items = (data.get("mission") or {}).get("items") or []
    for item in items:
        params = item.get("params") or [0.0] * 7
        wp = Waypoint(
            lat=float(params[4]),
            lon=float(params[5]),
            alt=float(params[6]),
            delay=float(params[0]),
            acceptance_radius=float(params[1]),
            orbit=float(params[2]),
            yaw=float(params[3]),
            command=int(item.get("command", 16)),
            frame=int(item.get("frame", 3)),
            autocontinue=1 if item.get("autoContinue", True) else 0,
        )
        wp.seq = len(mission._waypoints)
        mission._waypoints.append(wp)
    return mission


def to_qgc_plan(mission: Mission, cruise_speed: float = 10.0, hover_speed: float = 5.0) -> dict:
    """Serialize a Mission to a QGroundControl ``.plan`` dict.

    Home is ``mission.home`` (falls back to 0,0,0 when unset).
    """
    home = mission.home or (0.0, 0.0, 0.0)
    items = []
    for wp in mission._waypoints:
        items.append(
            {
                "AMSLAltAboveTerrain": None,
                "Altitude": wp.alt,
                "AltitudeMode": 0 if wp.frame == 0 else 1,
                "autoContinue": bool(wp.autocontinue),
                "command": wp.command,
                "doJumpId": None,
                "frame": wp.frame,
                "params": [
                    wp.delay,
                    wp.acceptance_radius,
                    wp.orbit,
                    wp.yaw,
                    wp.lat,
                    wp.lon,
                    wp.alt,
                ],
                "type": "SimpleItem",
                "coordinate": [wp.lat, wp.lon],
                "relativeAltitude": wp.frame != 0,
            }
        )
    return {
        "fileType": "Plan",
        "version": 1,
        "groundStation": "mavplan",
        "mission": {
            "cruiseSpeed": cruise_speed,
            "hoverSpeed": hover_speed,
            "vehicleType": 2,  # MAV_TYPE_QUADROTOR
            "firmwareType": 12,  # MAV_AUTOPILOT_ARDUPILOTMEGA
            "plannedHomePosition": [home[0], home[1], home[2]],
            "items": items,
        },
        "geoFence": {"circles": [], "polygons": [], "version": 1},
        "rallyPoints": {"points": [], "version": 1},
    }


def save_qgc_plan(mission: Mission, path: str | Path, **kwargs) -> None:
    """Write a Mission as a QGroundControl ``.plan`` JSON file."""
    Path(path).write_text(json.dumps(to_qgc_plan(mission, **kwargs), indent=2), encoding="utf-8")
