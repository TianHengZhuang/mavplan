"""Scenario presets (v1.6 training operations).

Loads CAAC-style training scenarios from ``scenarios/*.toml`` files and
materialises them into a ``TaskSpec`` plus a ``Mission`` so an instructor
can one-shot an entire class brief.

A scenario TOML file has the following shape:

    [meta]
    name = "rectangle_patrol"
    title_zh = "矩形巡检"
    title_en = "Rectangle patrol"
    difficulty = "easy"
    description = "..."

    [home]
    lat = 31.230
    lon = 121.470
    alt = 0.0

    [task]
    altitude_min = 40.0
    altitude_max = 60.0
    speed_min = 8.0
    speed_max = 12.0
    max_time_s = 600.0
    max_distance_m = 5000.0

    [[required]]
    name = "A"
    lat = 31.232
    lon = 121.472
    radius_m = 20.0
    kind = "point"

    [[no_fly_zones]]
    name = "school"
    lat = 31.235
    lon = 121.475
    radius_m = 50.0
    kind = "circle"

    [[waypoints]]
    lat = 31.232
    lon = 121.472
    alt = 50.0
    speed = 10.0

TOML is read with the stdlib ``tomllib`` (Python 3.11+); no external
dependency is needed.  The ``scenarios/`` directory bundled with the
package is the default search root; callers may point at any folder of
``.toml`` files via ``list_scenarios(scenarios_dir=...)``.

The module is deliberately small and synchronous: scenario presets are
tiny (a few KB each) and used at CLI speed.
"""
from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .mission import Mission
from .taskspec import CheckPoint, TaskSpec, Zone
from .waypoint import Waypoint

# Python 3.11+ has tomllib in stdlib; 3.10 needs the backport. The project
# requires Python >=3.10; if the import fails the rest of the module is
# unusable but a clear ImportError is raised when callers try to read
# scenarios, not at module import time.
if sys.version_info >= (3, 11):
    import tomllib as _toml  # noqa: F401  (re-exported below)
else:  # pragma: no cover - requires tomli backport at runtime
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "scenario.py needs tomllib (Python 3.11+) or the 'tomli' package "
            "on Python 3.10. Install tomli or upgrade Python to use "
            "mavplan scenario presets."
        ) from exc


@dataclass
class ScenarioSpec:
    """One loaded scenario file.

    Attributes:
        name:        Scenario id (filename stem).
        title_zh:    Chinese title for CLI display.
        title_en:    English title for CLI display.
        difficulty:  easy / medium / hard (informational).
        description: Free-text scenario description.
        task:        Materialised TaskSpec (with home, required, zones).
        waypoints:   Materialised list[Waypoint] for the canonical mission.
        source_path: Filesystem path the scenario was loaded from.
    """
    name: str
    title_zh: str
    title_en: str
    difficulty: str
    description: str
    task: TaskSpec
    waypoints: list[Waypoint] = field(default_factory=list)
    source_path: Optional[Path] = None

    def title(self, lang: str = "zh-CN") -> str:
        if lang.startswith("en"):
            return self.title_en or self.title_zh or self.name
        return self.title_zh or self.title_en or self.name


# ----------------------------------------------------------------------
# Filesystem helpers
# ----------------------------------------------------------------------

def default_scenarios_dir() -> Path:
    """Return the bundled ``scenarios/`` directory next to the package."""
    return Path(__file__).resolve().parent.parent.parent / "scenarios"


def list_scenarios(scenarios_dir: Optional[Path] = None) -> list[str]:
    """List scenario names available in ``scenarios_dir`` (or the bundled dir).

    Names are the file stems (without ``.toml`` extension), sorted.
    """
    root = Path(scenarios_dir) if scenarios_dir else default_scenarios_dir()
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.toml"))


def load_scenario(name: str, scenarios_dir: Optional[Path] = None) -> ScenarioSpec:
    """Load a scenario by name and return a fully-materialised ``ScenarioSpec``."""
    root = Path(scenarios_dir) if scenarios_dir else default_scenarios_dir()
    path = root / f"{name}.toml"
    if not path.is_file():
        raise FileNotFoundError(f"scenario not found: {path}")
    with open(path, "rb") as f:
        data = _toml.load(f)

    meta = data.get("meta", {})
    home = data.get("home", {})
    task = data.get("task", {})

    task_spec = TaskSpec(
        name=str(meta.get("name", name)),
        description=str(meta.get("description", "")),
        difficulty=str(meta.get("difficulty", "easy")),
        home=(
            float(home.get("lat", 31.20)),
            float(home.get("lon", 121.40)),
            float(home.get("alt", 0.0)),
        ),
        required=[CheckPoint.from_dict(d) for d in data.get("required", [])],
        altitude_range=(
            float(task.get("altitude_min", 50.0)),
            float(task.get("altitude_max", 80.0)),
        ),
        speed_range=(
            float(task.get("speed_min", 8.0)),
            float(task.get("speed_max", 12.0)),
        ),
        max_time_s=float(task.get("max_time_s", 600.0)),
        max_distance_m=float(task.get("max_distance_m", 5000.0)),
        no_fly_zones=[Zone.from_dict(d) for d in data.get("no_fly_zones", [])],
    )

    waypoints: list[Waypoint] = []
    for w in data.get("waypoints", []):
        wp = Waypoint(
            lat=float(w["lat"]),
            lon=float(w["lon"]),
            alt=float(w.get("alt", task_spec.altitude_range[0])),
            speed=float(w.get("speed", task_spec.speed_range[0])),
        )
        waypoints.append(wp)

    return ScenarioSpec(
        name=str(meta.get("name", name)),
        title_zh=str(meta.get("title_zh", meta.get("title", name))),
        title_en=str(meta.get("title_en", meta.get("title", name))),
        difficulty=str(meta.get("difficulty", "easy")),
        description=str(meta.get("description", "")),
        task=task_spec,
        waypoints=waypoints,
        source_path=path,
    )


def materialise_mission(scenario: ScenarioSpec, name: Optional[str] = None) -> Mission:
    """Convert a ``ScenarioSpec`` to a populated ``Mission`` instance."""
    mission = Mission(name=name or scenario.name)
    home = scenario.task.home
    mission.add_waypoint(
        lat=home[0],
        lon=home[1],
        alt=home[2],
        speed=scenario.task.speed_range[0],
    )
    for w in scenario.waypoints:
        mission.add_waypoint(
            lat=w.lat,
            lon=w.lon,
            alt=w.alt,
            speed=w.speed,
            delay=w.delay,
            yaw=w.yaw,
            acceptance_radius=w.acceptance_radius,
        )
    return mission


def validate_scenario(scenario: ScenarioSpec) -> list[str]:
    """Return a list of human-readable validation errors (empty when valid)."""
    return scenario.task.validate()