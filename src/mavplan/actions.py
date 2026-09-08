"""MAV_CMD constants and helpers for navigation and DO_* action items.

Values follow the MAVLink common message set (mavlink.io / pymavlink).
Only the subset commonly used in mission files is listed; unknown numeric
commands pass through unchanged everywhere in mavplan.
"""
from __future__ import annotations

# --- Navigation commands ---------------------------------------------------
NAV_WAYPOINT = 16
NAV_LOITER_UNLIM = 17
NAV_LOITER_TURNS = 18
NAV_LOITER_TIME = 19
NAV_RETURN_TO_LAUNCH = 20
NAV_LAND = 21
NAV_TAKEOFF = 22
NAV_SPLINE_WAYPOINT = 82
NAV_VTOL_TAKEOFF = 84
NAV_VTOL_LAND = 85

# --- DO_* action commands ---------------------------------------------------
DO_JUMP = 177
DO_CHANGE_SPEED = 178
DO_SET_HOME = 179
DO_SET_RELAY = 181
DO_REPEAT_RELAY = 182
DO_SET_SERVO = 183
DO_REPEAT_SERVO = 184
DO_SET_ROI_LOCATION = 195
DO_SET_ROI_WPNEXT_OFFSET = 196
DO_SET_ROI_NONE = 197
DO_SET_ROI = 201  # legacy alias, superseded by DO_SET_ROI_LOCATION
DO_DIGICAM_CONTROL = 203
DO_MOUNT_CONTROL = 205
DO_SET_CAM_TRIGG_DIST = 206
DO_FENCE_ENABLE = 207
DO_PARACHUTE = 208
DO_GRIPPER = 211
DO_SET_CAM_TRIGG_INTERVAL = 214

#: Canonical short name (no MAV_CMD_ prefix) per command id.
CMD_NAMES: dict[int, str] = {
    16: "NAV_WAYPOINT",
    17: "NAV_LOITER_UNLIM",
    18: "NAV_LOITER_TURNS",
    19: "NAV_LOITER_TIME",
    20: "NAV_RETURN_TO_LAUNCH",
    21: "NAV_LAND",
    22: "NAV_TAKEOFF",
    82: "NAV_SPLINE_WAYPOINT",
    84: "NAV_VTOL_TAKEOFF",
    85: "NAV_VTOL_LAND",
    177: "DO_JUMP",
    178: "DO_CHANGE_SPEED",
    179: "DO_SET_HOME",
    181: "DO_SET_RELAY",
    182: "DO_REPEAT_RELAY",
    183: "DO_SET_SERVO",
    184: "DO_REPEAT_SERVO",
    195: "DO_SET_ROI_LOCATION",
    196: "DO_SET_ROI_WPNEXT_OFFSET",
    197: "DO_SET_ROI_NONE",
    201: "DO_SET_ROI",
    203: "DO_DIGICAM_CONTROL",
    205: "DO_MOUNT_CONTROL",
    206: "DO_SET_CAM_TRIGG_DIST",
    207: "DO_FENCE_ENABLE",
    208: "DO_PARACHUTE",
    211: "DO_GRIPPER",
    214: "DO_SET_CAM_TRIGG_INTERVAL",
}

#: Accepted textual aliases (without MAV_CMD_ prefix) mapped to command ids.
NAME_ALIASES: dict[str, int] = {
    name.lower(): cmd for cmd, name in CMD_NAMES.items()
}
NAME_ALIASES.update(
    {
        "rtl": NAV_RETURN_TO_LAUNCH,
        "waypoint": NAV_WAYPOINT,
        "takeoff": NAV_TAKEOFF,
        "land": NAV_LAND,
        "spline": NAV_SPLINE_WAYPOINT,
        "spline_waypoint": NAV_SPLINE_WAYPOINT,
        "jump": DO_JUMP,
        "change_speed": DO_CHANGE_SPEED,
        "speed": DO_CHANGE_SPEED,
        "set_home": DO_SET_HOME,
        "set_servo": DO_SET_SERVO,
        "set_relay": DO_SET_RELAY,
        "camera_trigger_dist": DO_SET_CAM_TRIGG_DIST,
        "cam_trigg_dist": DO_SET_CAM_TRIGG_DIST,
        "trigger_dist": DO_SET_CAM_TRIGG_DIST,
        "camera_interval": DO_SET_CAM_TRIGG_INTERVAL,
        "cam_trigg_interval": DO_SET_CAM_TRIGG_INTERVAL,
        "trigger_interval": DO_SET_CAM_TRIGG_INTERVAL,
        "gripper": DO_GRIPPER,
        "parachute": DO_PARACHUTE,
        "fence_enable": DO_FENCE_ENABLE,
        "digicam_control": DO_DIGICAM_CONTROL,
        "mount_control": DO_MOUNT_CONTROL,
        "roi": DO_SET_ROI_LOCATION,
        "roi_location": DO_SET_ROI_LOCATION,
    }
)

#: First command id of the DO_* action range (for classification).
_ACTION_RANGE_START = 176


def command_id(command: int | str) -> int | None:
    """Resolve a command to its numeric MAV_CMD id.

    Accepts an int (returned as-is), or a name such as ``"NAV_WAYPOINT"``,
    ``"MAV_CMD_NAV_WAYPOINT"``, ``"DO_JUMP"`` or any alias in NAME_ALIASES
    (case-insensitive).  Returns None for unknown names.
    """
    if isinstance(command, int):
        return command
    name = str(command).strip().upper()
    if name.startswith("MAV_CMD_"):
        name = name[len("MAV_CMD_"):]
    return NAME_ALIASES.get(name.lower())


def command_name(command: int) -> str:
    """Short display name for a command id, e.g. ``DO_JUMP``."""
    return CMD_NAMES.get(command, f"UNKNOWN({command})")


def is_action(command: int) -> bool:
    """True for DO_* action items (as opposed to NAV_* navigation items)."""
    return command >= _ACTION_RANGE_START
