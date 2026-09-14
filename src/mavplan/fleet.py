"""Fleet model for multi-drone teaching missions (v1.15 web+CLI)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Optional

Airframe = Literal["multirotor", "fixedwing", "vtol"]
DroneStatus = Literal["planned", "ready", "flying", "landed"]
DroneRole = Literal["lead", "wingman", "standby"]

_NAME_RE = re.compile(r"^[一-鿿A-Za-z0-9_\-]{1,32}$")
_CALLSIGN_RE = re.compile(r"^[A-Za-z0-9_\-]{1,16}$")


@dataclass
class Drone:
    """One aircraft in a mission fleet."""

    id: str
    name: str
    callsign: str = ""
    model: str = ""
    airframe: Airframe = "multirotor"
    battery_wh: float = 77.0
    max_alt_m: float = 120.0
    max_range_m: float = 8000.0
    cruise_speed_ms: float = 10.0
    role: DroneRole = "wingman"
    status: DroneStatus = "planned"
    home: Optional[list[float]] = None  # [lat, lon, alt]
    payload: dict[str, Any] = field(default_factory=dict)
    mission_ref: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Drone":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            callsign=str(data.get("callsign") or ""),
            model=str(data.get("model") or ""),
            airframe=data.get("airframe") or "multirotor",  # type: ignore[arg-type]
            battery_wh=float(data.get("battery_wh") or 77.0),
            max_alt_m=float(data.get("max_alt_m") or 120.0),
            max_range_m=float(data.get("max_range_m") or 8000.0),
            cruise_speed_ms=float(data.get("cruise_speed_ms") or 10.0),
            role=data.get("role") or "wingman",  # type: ignore[arg-type]
            status=data.get("status") or "planned",  # type: ignore[arg-type]
            home=list(data["home"]) if isinstance(data.get("home"), (list, tuple)) else None,
            payload=dict(data.get("payload") or {}),
            mission_ref=data.get("mission_ref"),
        )


@dataclass
class Fleet:
    """Mission fleet container. Web stores the same JSON shape."""

    mission_name: str = "Untitled Mission"
    drones: list[Drone] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.drones)

    def get(self, drone_id: str) -> Optional[Drone]:
        for d in self.drones:
            if d.id == drone_id:
                return d
        return None

    def by_name(self, name: str) -> Optional[Drone]:
        for d in self.drones:
            if d.name == name:
                return d
        return None

    def lead(self) -> Optional[Drone]:
        for d in self.drones:
            if d.role == "lead":
                return d
        return self.drones[0] if self.drones else None

    def add(self, drone: Drone) -> Drone:
        errors = validate_drone(drone, existing=self.drones)
        if errors:
            raise ValueError("; ".join(errors))
        if not drone.id:
            drone.id = next_drone_id(self.drones)
        self.drones.append(drone)
        if drone.role == "lead":
            for other in self.drones:
                if other.id != drone.id and other.role == "lead":
                    other.role = "wingman"
        return drone

    def remove(self, drone_id: str) -> bool:
        before = len(self.drones)
        self.drones = [d for d in self.drones if d.id != drone_id]
        return len(self.drones) != before

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.mission_name:
            issues.append("mission_name is empty")
        if not self.drones:
            issues.append("fleet has no drones")
        if self.count > 20:
            issues.append("fleet exceeds teaching limit of 20 drones")
        names: set[str] = set()
        call_signs: set[str] = set()
        leads = 0
        for d in self.drones:
            if d.name in names:
                issues.append(f"duplicate drone name: {d.name}")
            names.add(d.name)
            if d.callsign:
                if d.callsign in call_signs:
                    issues.append(f"duplicate callsign: {d.callsign}")
                call_signs.add(d.callsign)
            if d.role == "lead":
                leads += 1
            issues.extend(validate_drone(d, existing=[]))
        if self.drones and leads == 0:
            issues.append("fleet has no lead drone")
        if leads > 1:
            issues.append("fleet has more than one lead drone")
        return issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_name": self.mission_name,
            "count": self.count,
            "drones": [d.to_dict() for d in self.drones],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Fleet":
        drones = [Drone.from_dict(d) for d in (data.get("drones") or [])]
        return cls(mission_name=str(data.get("mission_name") or "Untitled Mission"), drones=drones)

    @classmethod
    def single_from_mission(cls, mission_name: str, home: Optional[Iterable[float]] = None) -> "Fleet":
        """Default fleet: one lead multirotor bound to the main mission."""
        home_list = list(home) if home is not None else None
        lead = Drone(
            id="uav-1",
            name="主机",
            callsign="UAV-01",
            role="lead",
            status="planned",
            home=home_list,
        )
        return cls(mission_name=mission_name, drones=[lead])


def next_drone_id(drones: list[Drone]) -> str:
    n = 1
    used = {d.id for d in drones}
    while f"uav-{n}" in used:
        n += 1
    return f"uav-{n}"


def default_drone_name(index: int) -> str:
    return f"UAV-{index}"


def validate_drone(drone: Drone, existing: list[Drone]) -> list[str]:
    issues: list[str] = []
    if not drone.id:
        issues.append("drone.id is required")
    if not drone.name or not _NAME_RE.match(drone.name):
        issues.append(f"invalid drone.name: {drone.name!r}")
    if drone.callsign and not _CALLSIGN_RE.match(drone.callsign):
        issues.append(f"invalid callsign: {drone.callsign!r}")
    if drone.airframe not in ("multirotor", "fixedwing", "vtol"):
        issues.append(f"invalid airframe: {drone.airframe!r}")
    if drone.role not in ("lead", "wingman", "standby"):
        issues.append(f"invalid role: {drone.role!r}")
    if drone.status not in ("planned", "ready", "flying", "landed"):
        issues.append(f"invalid status: {drone.status!r}")
    if drone.battery_wh <= 0:
        issues.append("battery_wh must be > 0")
    if drone.max_alt_m <= 0 or drone.cruise_speed_ms <= 0:
        issues.append("max_alt_m and cruise_speed_ms must be > 0")
    for other in existing:
        if other.id == drone.id:
            issues.append(f"duplicate drone id: {drone.id}")
        if other.name == drone.name:
            issues.append(f"duplicate drone name: {drone.name}")
    return issues


def assign_formation_offsets(
    fleet: Fleet,
    spacing_m: float = 30.0,
) -> list[dict[str, Any]]:
    """Lateral east-offsets for teaching formation playback (lead = 0)."""
    ordered = sorted(
        fleet.drones,
        key=lambda d: (0 if d.role == "lead" else 1 if d.role == "wingman" else 2, d.id),
    )
    lead_i = next((i for i, d in enumerate(ordered) if d.role == "lead"), 0)
    out: list[dict[str, Any]] = []
    for i, d in enumerate(ordered):
        slot = i - lead_i
        out.append(
            {
                "id": d.id,
                "name": d.name,
                "role": d.role,
                "offset_east_m": slot * spacing_m,
                "slot": slot,
            }
        )
    return out
