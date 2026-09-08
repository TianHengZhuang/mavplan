"""mavplan — MAVLink mission planner."""
from .mission import Mission
from .waypoint import Waypoint
from .pattern import (
    LawnMowerParams,
    PolygonScanParams,
    OrbitParams,
    StartCorner,
    generate_lawnmower,
    generate_polygon_scan,
    generate_orbit,
)
from .flightlog import (
    FlightLog,
    FlightStats,
    FlightPoint,
    parse_csv,
    parse_mavplan_json,
    compare_to_plan,
)
from .kml_import import (
    KmlDocument,
    KmlWaypoint,
    parse_kml,
    MissionTemplate,
    get_templates,
    save_templates_library,
    load_templates_library,
)
from .mavlink_link import (
    MAVLinkConnection,
    ConnectionInfo,
    HeartbeatInfo,
    ConnectionState,
)
from .simulate import (
    BatteryModel,
    WindModel,
    WindDirection,
    SimulationParams,
    SimulationResult,
    estimate_energy,
    insert_takeoff_landing,
    check_geofence,
    generate_report,
)

__all__ = [
    "Mission",
    "Waypoint",
    "LawnMowerParams",
    "PolygonScanParams",
    "OrbitParams",
    "StartCorner",
    "generate_lawnmower",
    "generate_polygon_scan",
    "generate_orbit",
    "FlightLog",
    "FlightStats",
    "FlightPoint",
    "parse_csv",
    "parse_mavplan_json",
    "compare_to_plan",
    "KmlDocument",
    "KmlWaypoint",
    "parse_kml",
    "MissionTemplate",
    "get_templates",
    "save_templates_library",
    "load_templates_library",
    "MAVLinkConnection",
    "ConnectionInfo",
    "HeartbeatInfo",
    "ConnectionState",
    "BatteryModel",
    "WindModel",
    "WindDirection",
    "SimulationParams",
    "SimulationResult",
    "estimate_energy",
    "insert_takeoff_landing",
    "check_geofence",
    "generate_report",
]
__version__ = "1.0.0"
