"""KML file import and mission template library for mavplan."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .mission import Mission
from .waypoint import Waypoint


# ------------------------------------------------------------------
# KML import
# ------------------------------------------------------------------

@dataclass
class KmlWaypoint:
    """A waypoint extracted from a KML Placemark."""
    lat: float
    lon: float
    alt: float = 0.0
    name: str = ""
    description: str = ""
    # MAVLink-specific (optional)
    speed: float = 0.0
    delay: float = 0.0
    yaw: float = -9999.0


@dataclass
class KmlDocument:
    """A parsed KML document."""
    name: str = ""
    description: str = ""
    waypoints: list[KmlWaypoint] = field(default_factory=list)
    source_file: str = ""

    def to_mission(
        self,
        name: str = "",
        default_alt: float = 50.0,
        default_speed: float = 10.0,
    ) -> Mission:
        """Convert KML waypoints to a Mission.

        Args:
            name: Mission name (defaults to KML document name).
            default_alt: Altitude to use when KML has no altitude data.
            default_speed: Speed to assign to each waypoint.

        Returns:
            Mission with waypoints from the KML.
        """
        mission = Mission(name=name or self.name or "Imported from KML")
        for kw in self.waypoints:
            alt = kw.alt if kw.alt != 0.0 else default_alt
            mission.add_waypoint(
                lat=kw.lat,
                lon=kw.lon,
                alt=alt,
                speed=kw.speed if kw.speed > 0 else default_speed,
                delay=kw.delay,
                yaw=kw.yaw,
            )
        return mission


def parse_kml(path: str | Path) -> KmlDocument:
    """Parse a KML file and extract waypoints.

    Extracts coordinates from:
      - Placemark / Point / coordinates
      - Placemark / LineString / coordinates
      - Placemark / MultiGeometry / Point / coordinates
      - Placemark / MultiGeometry / LineString / coordinates

    Altitude is read from <altitude> or <gx:altitude> tags when present.
    Placemark names and descriptions are captured.

    Args:
        path: Path to the KML file.

    Returns:
        KmlDocument with extracted waypoints.

    Raises:
        ValueError: If the file cannot be parsed as KML.
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"File not found: {path}")

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML/KML file: {e}")
    except Exception as e:
        raise ValueError(f"Failed to read KML: {e}")

    # Register namespaces
    ns: dict[str, str] = {}
    for event, elem in ET.iterparse(path, events=["start-ns"]):
        if event == "start-ns":
            prefix, uri = elem
            ns[prefix if prefix else "default"] = uri
            ET.register_namespace(prefix if prefix else "default", uri)

    # Also register common namespaces manually to avoid issues
    ET.register_namespace("", "http://www.opengis.net/kml/2.2")
    ET.register_namespace("gx", "http://www.google.com/kml/ext/2.2")
    ET.register_namespace("kml", "http://www.opengis.net/kml/2.2")

    doc = KmlDocument(source_file=str(path))

    # Extract document name/description
    ns_map = {
        "kml": "http://www.opengis.net/kml/2.2",
        "gx": "http://www.google.com/kml/ext/2.2",
    }
    doc_name = _find_text(root, ".//kml:Document/kml:name", ns_map) or ""
    doc_desc = _find_text(root, ".//kml:Document/kml:description", ns_map) or ""
    doc.name = doc_name
    doc.description = doc_desc

    # Find all Placemarks
    placemarks = _find_all(root, ".//kml:Placemark", ns_map)

    for placemark in placemarks:
        pm_name = _find_text(placemark, "kml:name", ns_map) or ""
        pm_desc = _find_text(placemark, "kml:description", ns_map) or ""

        # Extract coordinates from various geometry types
        coords: list[tuple[float, float, float]] = []

        for geom in ["Point", "LineString", "Polygon"]:
            coord_nodes = _find_all(placemark, f"kml:{geom}/kml:coordinates", ns_map)
            for node in coord_nodes:
                parsed = _parse_coordinates_text(node.text or "")
                coords.extend(parsed)

            # MultiGeometry
            for mg_geom in _find_all(placemark, f"kml:MultiGeometry/kml:{geom}", ns_map):
                mg_coord_nodes = _find_all(mg_geom, "kml:coordinates", ns_map)
                for node in mg_coord_nodes:
                    parsed = _parse_coordinates_text(node.text or "")
                    coords.extend(parsed)

        for lat, lon, alt in coords:
            kw = KmlWaypoint(
                lat=lat,
                lon=lon,
                alt=alt,
                name=pm_name,
                description=pm_desc,
            )
            doc.waypoints.append(kw)

    return doc


def _find_text(root: ET.Element, xpath: str, ns: dict[str, str]) -> Optional[str]:
    try:
        elem = root.find(xpath, ns)
        if elem is not None and elem.text:
            return elem.text.strip()
    except Exception:
        pass
    return None


def _find_all(root: ET.Element, xpath: str, ns: dict[str, str]) -> list[ET.Element]:
    try:
        return list(root.findall(xpath, ns))
    except Exception:
        return []


def _parse_coordinates_text(text: str) -> list[tuple[float, float, float]]:
    """Parse KML coordinates text: 'lon,lat,alt lon,lat,alt ...'"""
    results = []
    text = text.strip()
    if not text:
        return results

    for segment in text.split():
        segment = segment.strip()
        if not segment:
            continue
        parts = segment.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0].strip())
            lat = float(parts[1].strip())
            alt = float(parts[2].strip()) if len(parts) >= 3 else 0.0
            results.append((lat, lon, alt))
        except ValueError:
            continue
    return results


# ------------------------------------------------------------------
# Mission templates
# ------------------------------------------------------------------

@dataclass
class MissionTemplate:
    """A reusable mission template."""
    name: str
    description: str
    category: str  # e.g. "survey", "inspection", "mapping", "emergency"
    mission: Mission

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "mission": self.mission.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> MissionTemplate:
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            category=data.get("category", "custom"),
            mission=Mission.from_dict(data["mission"]),
        )


# Built-in templates library
def get_templates() -> list[MissionTemplate]:
    """Return the built-in mission template library.

    Templates cover common drone operations. Each can be loaded,
    customized, and saved as a new mission.
    """
    templates: list[MissionTemplate] = []

    # --- Survey / Mapping ---
    t = MissionTemplate(
        name="Large Area Survey",
        description="500x500m area survey with 20m lane spacing at 50m altitude",
        category="survey",
        mission=Mission(name="Large Area Survey"),
    )
    from .pattern import LawnMowerParams, generate_lawnmower
    params = LawnMowerParams(
        corner1=(31.230, 121.470),
        corner2=(31.2345, 121.4745),
        altitude=50.0,
        speed=10.0,
        lane_spacing=20.0,
    )
    for wp in generate_lawnmower(params):
        t.mission.add_waypoint(**wp.to_dict())
    templates.append(t)

    # --- Pipeline Inspection ---
    t2 = MissionTemplate(
        name="Pipeline Inspection",
        description="Linear corridor survey along a pipeline: 2km straight route at 30m altitude",
        category="inspection",
        mission=Mission(name="Pipeline Inspection"),
    )
    # 20 waypoints along a straight line
    for i in range(20):
        lat = 31.230 + i * 0.001
        t2.mission.add_waypoint(lat=lat, lon=121.470, alt=30.0, speed=8.0)
    templates.append(t2)

    # --- Emergency Survey Grid ---
    t3 = MissionTemplate(
        name="Emergency Survey Grid",
        description="Quick 100x100m survey grid at 40m altitude for emergency response",
        category="emergency",
        mission=Mission(name="Emergency Survey Grid"),
    )
    params3 = LawnMowerParams(
        corner1=(31.230, 121.470),
        corner2=(31.231, 121.471),
        altitude=40.0,
        speed=15.0,
        lane_spacing=10.0,
    )
    for wp in generate_lawnmower(params3):
        t3.mission.add_waypoint(**wp.to_dict())
    templates.append(t3)

    # --- Perimeter Patrol ---
    t4 = MissionTemplate(
        name="Perimeter Patrol",
        description="Circular orbit patrol: 8 waypoints around a 50m radius circle",
        category="inspection",
        mission=Mission(name="Perimeter Patrol"),
    )
    from .pattern import OrbitParams, generate_orbit
    orbit_params = OrbitParams(
        center_lat=31.231, center_lon=121.472,
        radius=50.0, altitude=50.0, num_points=8,
    )
    for wp in generate_orbit(orbit_params):
        t4.mission.add_waypoint(**wp.to_dict())
    templates.append(t4)

    # --- Mapping Mission ---
    t5 = MissionTemplate(
        name="Mapping Mission",
        description="400x400m orthomosaic mapping at 80m altitude, 15m lane spacing",
        category="mapping",
        mission=Mission(name="Mapping Mission"),
    )
    params5 = LawnMowerParams(
        corner1=(31.228, 121.468),
        corner2=(31.232, 121.472),
        altitude=80.0,
        speed=8.0,
        lane_spacing=15.0,
    )
    for wp in generate_lawnmower(params5):
        t5.mission.add_waypoint(**wp.to_dict())
    templates.append(t5)

    return templates


def save_templates_library(path: str | Path) -> None:
    """Save the built-in template library to a JSON file.

    Templates can be loaded with load_templates_library() and
    customized before use.

    Args:
        path: Output path for the templates JSON file.
    """
    templates = get_templates()
    data = {
        "version": "1.0",
        "templates": [t.to_dict() for t in templates],
    }
    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_templates_library(path: str | Path) -> list[MissionTemplate]:
    """Load a templates library JSON file.

    Args:
        path: Path to the templates JSON file.

    Returns:
        List of MissionTemplate objects.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [MissionTemplate.from_dict(t) for t in data["templates"]]


def list_templates() -> None:
    """Print all built-in templates to stdout."""
    templates = get_templates()
    by_category: dict[str, list[MissionTemplate]] = {}
    for t in templates:
        by_category.setdefault(t.category, []).append(t)

    print("  Available mission templates:")
    for cat, ts in sorted(by_category.items()):
        print(f"\n  [{cat.upper()}]")
        for t in ts:
            print(f"    - {t.name}")
            print(f"      {t.description}")
            print(f"      {len(t.mission)} waypoints")
