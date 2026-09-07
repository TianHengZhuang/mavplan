"""MAVLink waypoint definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Waypoint:
    """A single MAVLink mission waypoint.

    Args:
        lat: Latitude in degrees (-90 to 90).
        lon: Longitude in degrees (-180 to 180).
        alt: Altitude in metres (relative to home / frame datum).
        speed: Desired speed in m/s for this leg (0 = use default).
        delay: Hold time in seconds at this waypoint before proceeding.
        yaw: Heading in degrees (-9999 = no heading constraint).
        acceptance_radius: Acceptance radius in metres (default 2 m).
        orbit: Orbit / circling radius in metres (0 = no orbit).
        command: MAVLink navigation command (default NAV_WAYPOINT = 16).
        frame: Coordinate frame. 0=global, 3=global relative alt.
        autocontinue: Auto-continue to next waypoint (1=yes).
    """

    lat: float
    lon: float
    alt: float
    speed: float = 0.0
    delay: float = 0.0
    yaw: float = -9999.0
    acceptance_radius: float = 2.0
    orbit: float = 0.0
    command: int = 16  # MAV_CMD_NAV_WAYPOINT
    frame: int = 3  # MAV_FRAME_GLOBAL_RELATIVE_ALT
    autocontinue: int = 1

    seq: int = 0  # Set automatically by Mission.add_waypoint()

    def validate(self) -> list[str]:
        """Return a list of validation error messages (empty if valid)."""
        errors = []
        if not -90 <= self.lat <= 90:
            errors.append(f"Latitude {self.lat} is out of range (-90 to 90)")
        if not -180 <= self.lon <= 180:
            errors.append(f"Longitude {self.lon} is out of range (-180 to 180)")
        if self.alt < -1000 or self.alt > 50000:
            errors.append(f"Altitude {self.alt}m is outside safe range (-1000 to 50000)")
        if self.speed < 0:
            errors.append(f"Speed {self.speed} cannot be negative")
        if self.delay < 0:
            errors.append(f"Delay {self.delay} cannot be negative")
        if not -180 <= self.yaw <= 360 and self.yaw != -9999:
            errors.append(f"Yaw {self.yaw} is not in range (-180 to 360) or -9999")
        return errors

    def distance_to(self, other: Waypoint) -> float:
        """Haversine distance to another waypoint in metres."""
        import math

        R = 6371000  # Earth radius in metres
        phi1 = math.radians(self.lat)
        phi2 = math.radians(other.lat)
        dphi = math.radians(other.lat - self.lat)
        dlambda = math.radians(other.lon - self.lon)

        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def bearing_to(self, other: Waypoint) -> float:
        """Initial bearing to another waypoint in degrees (0-360)."""
        import math

        phi1 = math.radians(self.lat)
        phi2 = math.radians(other.lat)
        dlambda = math.radians(other.lon - self.lon)

        x = math.sin(dlambda) * math.cos(phi2)
        y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
        bearing = math.degrees(math.atan2(x, y))
        return (bearing + 360) % 360

    def to_mavlink_item(self) -> dict:
        """Return MAVLink MISSION_ITEM-compatible dict."""
        return {
            "seq": self.seq,
            "frame": self.frame,
            "command": self.command,
            "current": 0,
            "autocontinue": self.autocontinue,
            "param1": self.delay,
            "param2": self.acceptance_radius,
            "param3": self.orbit,
            "param4": self.yaw,
            "x": self.lat,
            "y": self.lon,
            "z": self.alt,
        }

    def to_dict(self) -> dict:
        """Serializable dict representation."""
        return {
            "seq": self.seq,
            "lat": self.lat,
            "lon": self.lon,
            "alt": self.alt,
            "speed": self.speed,
            "delay": self.delay,
            "yaw": self.yaw,
            "acceptance_radius": self.acceptance_radius,
            "orbit": self.orbit,
            "command": self.command,
            "frame": self.frame,
            "autocontinue": self.autocontinue,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Waypoint:
        """Reconstruct from a dict (e.g. loaded from JSON)."""
        return cls(
            seq=data.get("seq", 0),
            lat=data["lat"],
            lon=data["lon"],
            alt=data["alt"],
            speed=data.get("speed", 0.0),
            delay=data.get("delay", 0.0),
            yaw=data.get("yaw", -9999.0),
            acceptance_radius=data.get("acceptance_radius", 2.0),
            orbit=data.get("orbit", 0.0),
            command=data.get("command", 16),
            frame=data.get("frame", 3),
            autocontinue=data.get("autocontinue", 1),
        )
