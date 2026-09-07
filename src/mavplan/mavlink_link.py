"""MAVLink communication: connect to autopilot and upload/download missions.

Requires pymavlink:  pip install pymavlink

Supported autopilots: PX4, ArduPilot (Copter, Plane, Rover, Boat)
Connection: Serial (USB telemetry radio / SiK radio) or UDP (WiFi)

Example:
    link = MAVLinkConnection.connect("serial:/dev/ttyUSB0:57600")
    link.upload_mission(my_mission)
    link.close()
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

# ------------------------------------------------------------------
# pymavlink dependency check
# ------------------------------------------------------------------

try:
    from pymavlink import mavutil
    _HAVE_PYMAVLINK = True
except ImportError:
    _HAVE_PYMAVLINK = False


# ------------------------------------------------------------------
# Enums
# ------------------------------------------------------------------

class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# ------------------------------------------------------------------
# Dataclasses
# ------------------------------------------------------------------

@dataclass
class ConnectionInfo:
    """Connection metadata."""
    device: str
    baudrate: int = 57600
    system_id: int = 255
    component_id: int = 0
    target_system: int = 1
    target_component: int = 1


@dataclass
class HeartbeatInfo:
    """Last heartbeat data from the autopilot."""
    system_status: str = ""
    autopilot_type: str = ""
    base_mode: int = 0
    custom_mode: int = 0
    system_type: str = ""
    armed: bool = False
    guided: bool = False
    auto_mode: bool = False
    timestamp: float = 0.0


@dataclass
class MAVLinkConnection:
    """Active MAVLink connection to an autopilot."""
    _mav: Optional[object] = None
    _thread: Optional[threading.Thread] = None
    _running: bool = False
    _state: ConnectionState = field(default_factory=ConnectionState.DISCONNECTED)
    info: ConnectionInfo = field(default_factory=ConnectionInfo)
    last_heartbeat: HeartbeatInfo = field(default_factory=HeartbeatInfo)
    _on_heartbeat: Optional[Callable[[HeartbeatInfo], None]] = None
    _last_msg_time: float = 0.0

    @classmethod
    def connect(cls, device: str, **kwargs) -> MAVLinkConnection:
        """Connect to an autopilot.

        Connection strings:
          serial:/dev/ttyUSB0:57600     (Linux/macOS)
          serial:COM3:57600              (Windows)
          udp:127.0.0.1:14550            (localhost UDP)
          udpin:127.0.0.1:14550          (UDP server mode)
          tcp:127.0.0.1:5760             (TCP client)

        Args:
            device: Connection string.
            **kwargs: Additional pymavlink options (baudrate, source_system, etc.)

        Returns:
            MAVLinkConnection instance.

        Raises:
            ImportError: If pymavlink is not installed.
            ConnectionError: If the connection fails.
        """
        if not _HAVE_PYMAVLINK:
            raise ImportError(
                "pymavlink is required for MAVLink support.\n"
                "Install with: pip install pymavlink\n"
                "Or: pip install mavplan[mavlink]"
            )

        conn = cls()
        conn.info = ConnectionInfo(device=device)
        conn._state = ConnectionState.CONNECTING

        try:
            conn_str = device
            if device.startswith("serial:"):
                parts = device[7:].rsplit(":", 1)
                dev_path = parts[0]
                baud = int(parts[1]) if len(parts) > 1 else 57600
                conn_str = dev_path
                kwargs.setdefault("baud", baud)
                conn.info.baudrate = baud
            elif device.startswith("udp") or device.startswith("tcp"):
                pass

            kwargs.setdefault("source_system", 255)
            kwargs.setdefault("source_component", 0)
            conn.info.system_id = kwargs.get("source_system", 255)

            mav = mavutil.mavlink_connection(conn_str, **kwargs)
            conn._mav = mav

            mav.wait_heartbeat(timeout=30)
            hb = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=30)
            if hb is None:
                raise ConnectionError("No heartbeat received from autopilot")

            conn._update_heartbeat(hb)
            conn._state = ConnectionState.CONNECTED
            conn.info.target_system = mav.target_system
            conn.info.target_component = mav.target_component

            conn._running = True
            conn._thread = threading.Thread(target=conn._read_loop, daemon=True)
            conn._thread.start()

            return conn

        except Exception as e:
            conn._state = ConnectionState.ERROR
            conn._running = False
            raise ConnectionError(f"Failed to connect to {device}: {e}")

    def _read_loop(self) -> None:
        """Background thread: read messages and update heartbeat."""
        while self._running and self._mav:
            try:
                msg = self._mav.recv_msg()
                if msg is None:
                    time.sleep(0.01)
                    continue
                self._last_msg_time = time.time()
                if msg.get_type() == "HEARTBEAT":
                    self._update_heartbeat(msg)
                    if self._on_heartbeat:
                        try:
                            self._on_heartbeat(self.last_heartbeat)
                        except Exception:
                            pass
            except Exception:
                time.sleep(0.1)

    def _update_heartbeat(self, msg) -> None:
        autopy = {
            0: "GENERIC", 1: "RESERVED", 2: "SLUGS",
            3: "ARDUPILOTMEGA", 4: "OPENPILOT", 5: "GENERIC",
            6: "PPZ", 7: "UDB", 8: "FP", 9: "PX4",
            10: "SMACCMPILOT", 11: "AUTOQUAD", 12: "MAVRIX",
            13: "ARMIZU", 14: "AUAV", 15: "FPV", 16: "DJI",
            17: "RISING", 18: "ADU", 19: "ALIAS", 20: "SC",
            21: "MBDYNAMICS", 25: "FRSKY", 26: "END", 27: "HELIPILOT",
            28: "SR", 29: "EML", 30: "RADIO", 31: "OZ", 32: "ETH",
            33: "MWS", 34: "VI", 35: "BRIDG", 36: "NUCLEO",
            37: "CUAV", 38: "RFD", 39: "GNU", 40: "SW", 41: "BOX",
        }
        type_map = {
            0: "GENERIC", 1: "FIXED_WING", 2: "QUADROTOR", 3: "HELICOPTER",
            4: "ANTENNA_TRACKER", 5: "GCS", 6: "AIRSHIP", 7: "FREE_BALLOON",
            8: "ROCKET", 10: "GROUND_ROVER", 11: "SURFACE_BOAT",
            12: "SUBMARINE", 13: "HEXAROTOR", 14: "OCTOROTOR",
            15: "TRICOPTER", 16: "FLAPPING_WING", 17: "KITE",
            18: "ONBOARD_CONTROLLER", 19: "GIMBAL", 20: "ADSB",
            22: "COPTER", 23: "VTOL_DUOROTOR", 24: "VTOL_QUADROTOR",
            25: "VTOL_TILTROTOR", 27: "PRISM", 28: "ONBOARD_COMPANION",
        }
        armed = bool(msg.base_mode & 0x80)
        guided = bool(msg.base_mode & 0x40)

        self.last_heartbeat = HeartbeatInfo(
            system_status="ACTIVE" if armed else "STANDBY",
            autopilot_type=autopy.get(msg.autopilot, str(msg.autopilot)),
            base_mode=msg.base_mode,
            custom_mode=msg.custom_mode,
            system_type=type_map.get(msg.type, f"TYPE_{msg.type}"),
            armed=armed,
            guided=guided,
            auto_mode=guided,
            timestamp=time.time(),
        )

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED and self._mav is not None

    def wait_for_heartbeat(self, timeout: float = 10.0) -> bool:
        """Block until a heartbeat is received."""
        if not self._mav:
            return False
        hb = self._mav.recv_match(type="HEARTBEAT", blocking=True, timeout=timeout)
        if hb:
            self._update_heartbeat(hb)
            return True
        return False

    def upload_mission(self, mission) -> dict:
        """Upload a Mission to the autopilot.

        Args:
            mission: mavplan Mission object.

        Returns:
            Dict with upload result.
        """
        if not self._mav:
            return {"success": False, "waypoints_sent": 0, "message": "Not connected"}

        try:
            waypoints = mission.waypoints()
            if not waypoints:
                return {"success": False, "waypoints_sent": 0, "message": "Mission has no waypoints"}

            target = self._mav.target_system
            comp = self._mav.target_component

            self._mav.mav.mission_clear_all_send(target, comp)
            self._mav.recv_match(type="MISSION_ACK", timeout=5)

            self._mav.mav.mission_count_send(target, comp, len(waypoints))

            for i, wp in enumerate(waypoints):
                req = self._mav.recv_match(
                    type="MISSION_REQUEST", blocking=True, timeout=10
                )
                if req is None or req.seq != i:
                    return {
                        "success": False,
                        "waypoints_sent": i,
                        "message": f"Timeout waiting for waypoint {i} request",
                    }

                self._mav.mav.mission_item_send(
                    target, comp,
                    seq=i,
                    frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                    command=getattr(wp, "command", 16),
                    current=0,
                    autocontinue=1 if getattr(wp, "autocontinue", True) else 0,
                    param1=getattr(wp, "delay", 0.0),
                    param2=getattr(wp, "acceptance_radius", 0.0),
                    param3=0.0,
                    param4=math.radians(wp.yaw) if wp.yaw != -9999 else 0.0,
                    x=wp.lat,
                    y=wp.lon,
                    z=wp.alt,
                )

            ack = self._mav.recv_match(type="MISSION_ACK", blocking=True, timeout=10)
            if ack and ack.type == 0:
                return {
                    "success": True,
                    "waypoints_sent": len(waypoints),
                    "message": f"Uploaded {len(waypoints)} waypoints",
                }
            elif ack:
                return {
                    "success": False,
                    "waypoints_sent": len(waypoints),
                    "message": f"Mission ack: type={ack.type}",
                }
            else:
                return {
                    "success": False,
                    "waypoints_sent": len(waypoints),
                    "message": "No mission ack received",
                }

        except Exception as e:
            return {"success": False, "waypoints_sent": 0, "message": str(e)}

    def download_mission(self) -> tuple[bool, list]:
        """Download the current mission from the autopilot.

        Returns:
            Tuple of (success, waypoints_list_or_empty_list).
        """
        if not self._mav:
            return False, []

        try:
            target = self._mav.target_system
            comp = self._mav.target_component

            self._mav.mav.mission_request_list_send(target, comp)
            count_msg = self._mav.recv_match(type="MISSION_COUNT", blocking=True, timeout=10)
            if count_msg is None:
                return False, []

            count = count_msg.count
            if count == 0:
                return True, []

            waypoints = []
            for seq in range(count):
                self._mav.mav.mission_ack_send(target, comp, 0)
                item = self._mav.recv_match(type="MISSION_ITEM", blocking=True, timeout=10)
                if item is None:
                    return False, waypoints

                from .waypoint import Waypoint
                wp = Waypoint(
                    lat=item.x,
                    lon=item.y,
                    alt=item.z,
                    speed=0.0,
                    delay=item.param1,
                    yaw=math.degrees(item.param4) if item.param4 != 0 else -9999,
                    seq=item.seq,
                )
                waypoints.append(wp)

            return True, waypoints

        except Exception:
            return False, []

    def set_current_waypoint(self, seq: int) -> bool:
        """Set the active waypoint by sequence number."""
        if not self._mav:
            return False
        try:
            self._mav.mav.mission_set_current_send(
                self._mav.target_system, self._mav.target_component, seq
            )
            return True
        except Exception:
            return False

    def on_heartbeat(self, callback: Callable[[HeartbeatInfo], None]) -> None:
        """Register a callback for heartbeat events."""
        self._on_heartbeat = callback

    def close(self) -> None:
        """Close the MAVLink connection."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._mav:
            try:
                self._mav.close()
            except Exception:
                pass
            self._mav = None
        self._state = ConnectionState.DISCONNECTED
