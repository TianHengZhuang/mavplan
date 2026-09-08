"""Command-line interface for mavplan."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .mission import Mission
from .waypoint import Waypoint
from .actions import command_id, command_name
from .formats import load_mission_file, save_qgc_plan, to_qgc_plan, to_wpl
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
    parse_csv,
    parse_mavplan_json,
    compare_to_plan,
)
from .kml_import import (
    KmlDocument,
    parse_kml,
    get_templates,
    save_templates_library,
    list_templates,
)
from .mavlink_link import (
    MAVLinkConnection,
    ConnectionState,
)
from .simulate import (
    BatteryModel,
    WindModel,
    WindDirection,
    SimulationParams,
    estimate_energy,
    insert_takeoff_landing,
    check_geofence,
    generate_report,
)

MISSION_FILE = Path.home() / ".mavplan" / "mission.json"


def _ensure_dir():
    MISSION_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_mission() -> Mission:
    if MISSION_FILE.exists():
        try:
            return Mission.load(MISSION_FILE)
        except Exception:
            pass
    return Mission()


def _save_mission(mission: Mission) -> None:
    _ensure_dir()
    mission.save(MISSION_FILE)


# ------------------------------------------------------------------
# waypoint group
# ------------------------------------------------------------------
@click.group()
def waypoint() -> None:
    """Manage waypoints in the current mission."""
    pass


@waypoint.command()
@click.option("--lat", type=float, required=True, help="Latitude (-90 to 90)")
@click.option("--lon", type=float, required=True, help="Longitude (-180 to 180)")
@click.option("--alt", type=float, required=True, help="Altitude in metres")
@click.option("--speed", type=float, default=0.0, help="Speed in m/s (0=default)")
@click.option("--delay", type=float, default=0.0, help="Hold time in seconds")
@click.option("--yaw", type=float, default=-9999.0, help="Yaw heading in degrees")
@click.option("--save/--no-save", "auto_save", default=True, help="Auto-save mission")
def add(lat: float, lon: float, alt: float, speed: float, delay: float, yaw: float, auto_save: bool) -> None:
    """Add a waypoint to the mission."""
    wp = Waypoint(lat=lat, lon=lon, alt=alt, speed=speed, delay=delay, yaw=yaw)
    errors = wp.validate()
    if errors:
        click.echo(f"  Error: {errors[0]}", err=True)
        sys.exit(1)
    mission = _load_mission()
    wp = mission.add_waypoint(lat=lat, lon=lon, alt=alt, speed=speed, delay=delay, yaw=yaw)
    click.echo(f"  Added WP{wp.seq}: {lat:.7f}, {lon:.7f}, alt={alt:.1f}m")
    if auto_save:
        _save_mission(mission)


@waypoint.command("action")
@click.argument("after_seq", type=int)
@click.option("--command", "-c", required=True, help="MAV_CMD name, e.g. DO_CHANGE_SPEED or do_jump")
@click.option("--param1", "-p1", type=float, default=0.0, help="param1 for the command")
@click.option("--param2", "-p2", type=float, default=0.0, help="param2 for the command")
@click.option("--param3", "-p3", type=float, default=0.0, help="param3 for the command")
@click.option("--param4", "-p4", type=float, default=0.0, help="param4 for the command")
@click.option("--save/--no-save", "auto_save", default=True, help="Auto-save mission")
def insert_action(
    after_seq: int, command: str, param1: float, param2: float,
    param3: float, param4: float, auto_save: bool,
) -> None:
    """Insert a DO_* action item after WP<after_seq>.

    The action inherits the position of the preceding waypoint. Example::

        mavplan waypoint action 0 --command DO_CHANGE_SPEED --param1 5
    """
    mission = _load_mission()
    if after_seq < 0 or after_seq >= len(mission):
        click.echo(f"  Error: WP{after_seq} does not exist (have 0-{len(mission)-1})", err=True)
        sys.exit(1)
    cmd = command_id(command)
    if cmd is None:
        click.echo(f"  Error: unknown MAV_CMD '{command}'", err=True)
        sys.exit(1)
    act = mission.add_action(
        after_seq, cmd, param1=param1, param2=param2, param3=param3, param4=param4
    )
    click.echo(
        f"  Inserted {command_name(act.command)} after WP{after_seq} (now WP{act.seq})"
    )
    if auto_save:
        _save_mission(mission)


@waypoint.command()
def list() -> None:
    """List all waypoints in the current mission."""
    mission = _load_mission()
    if not mission.waypoints():
        click.echo("  (mission is empty)")
        return
    click.echo(f"  Mission: {mission.name}  ({len(mission)} waypoints)")
    click.echo("")
    for wp in mission.waypoints():
        yaw_str = f"yaw={wp.yaw:.0f}" if wp.yaw != -9999 else "yaw=N/A"
        suffix = f" [{command_name(wp.command)}]" if wp.command != 16 else ""
        click.echo(
            f"  WP{wp.seq}: lat={wp.lat:.7f} lon={wp.lon:.7f} "
            f"alt={wp.alt:.1f}m speed={wp.speed:.0f}m/s "
            f"delay={wp.delay:.0f}s {yaw_str}{suffix}"
        )


@waypoint.command()
@click.argument("seq", type=int)
@click.option("--save/--no-save", "auto_save", default=True)
@click.confirmation_option(prompt="Remove this waypoint?")
def remove(seq: int, auto_save: bool) -> None:
    """Remove a waypoint by sequence number."""
    mission = _load_mission()
    wps = mission.waypoints()
    if seq < 0 or seq >= len(wps):
        click.echo(f"  Error: WP{seq} does not exist (have 0-{len(wps)-1})", err=True)
        sys.exit(1)
    removed = wps[seq]
    del mission._waypoints[seq]
    # Re-sequence
    for i, wp in enumerate(mission._waypoints):
        wp.seq = i
    click.echo(f"  Removed WP{seq}: {removed.lat:.7f}, {removed.lon:.7f}")
    if auto_save:
        _save_mission(mission)


@waypoint.command()
def clear() -> None:
    """Clear all waypoints from the mission."""
    mission = Mission()
    _save_mission(mission)
    click.echo("  Mission cleared.")


# ------------------------------------------------------------------
# mission group
# ------------------------------------------------------------------
@click.group()
def mission() -> None:
    """Mission-level operations."""
    pass


@mission.command()
@click.option("--name", default="", help="Mission name")
def list(name: str) -> None:
    """Show current mission summary."""
    m = _load_mission()
    if name:
        m.name = name
        _save_mission(m)
        click.echo(f"  Mission name set to: {name}")
    else:
        click.echo(f"  Name: {m.name}")
        click.echo(f"  Waypoints: {len(m)}")
        if m.waypoints():
            click.echo(f"  Total distance: {m.total_distance()/1000:.2f} km")
            dur = m.estimated_duration()
            mins, secs = divmod(int(dur), 60)
            click.echo(f"  Est. duration: ~{mins}m {secs}s")


@mission.command()
@click.argument("path")
def load(path: str) -> None:
    """Load a mission from a .json file."""
    try:
        m = Mission.load(path)
        _save_mission(m)
        click.echo(f"  Loaded '{m.name}' ({len(m)} waypoints)")
    except Exception as e:
        click.echo(f"  Error loading {path}: {e}", err=True)
        sys.exit(1)


@mission.command("import")
@click.argument("path")
def import_file(path: str) -> None:
    """Import waypoints from WPL/.plan/.json (format auto-detected)."""
    try:
        m = load_mission_file(path)
    except Exception as e:
        click.echo(f"  Error importing {path}: {e}", err=True)
        sys.exit(1)
    _save_mission(m)
    home_str = f", home=({m.home[0]:.7f}, {m.home[1]:.7f}, {m.home[2]:.1f})" if m.home else ""
    click.echo(f"  Imported '{m.name}' ({len(m)} waypoints{home_str})")

@mission.command()
@click.argument("path")
def save(path: str) -> None:
    """Save the current mission to a .json file."""
    m = _load_mission()
    try:
        m.save(path)
        click.echo(f"  Saved '{m.name}' to {path}")
    except Exception as e:
        click.echo(f"  Error saving: {e}", err=True)
        sys.exit(1)


@mission.command()
def validate() -> None:
    """Validate the current mission."""
    m = _load_mission()
    errors = m.validate()
    if errors:
        click.echo("  Validation FAILED:")
        for e in errors:
            click.echo(f"    - {e}")
        sys.exit(1)
    else:
        click.echo("  Validation OK")


@mission.command("camera")
@click.option("--mode", type=click.Choice(["distance", "time"]), default="distance",
              help="Trigger every X metres of travel (distance) or every X seconds (time)")
@click.option("--value", type=float, required=True, help="Metres (distance) or seconds (time)")
@click.option("--after", "after_seq", type=int, default=0, help="Insert after this waypoint seq (default 0)")
@click.option("--save/--no-save", "auto_save", default=True, help="Auto-save mission")
def camera(mode: str, value: float, after_seq: int, auto_save: bool) -> None:
    """Insert a camera-trigger action (photo every X m / X s)."""
    m = _load_mission()
    if not m.waypoints():
        click.echo("  Error: mission is empty", err=True)
        sys.exit(1)
    if after_seq < 0 or after_seq >= len(m):
        click.echo(f"  Error: WP{after_seq} does not exist (have 0-{len(m)-1})", err=True)
        sys.exit(1)
    act = m.add_camera_trigger(mode, value, after_seq)
    unit = "m" if mode == "distance" else "s"
    click.echo(
        f"  Added {command_name(act.command)} every {value:g}{unit} after WP{after_seq} (now WP{act.seq})"
    )
    if auto_save:
        _save_mission(m)


# ------------------------------------------------------------------
# export group
# ------------------------------------------------------------------
@click.group()
def export() -> None:
    """Export the current mission to various formats."""
    pass


@export.command()
@click.option("--output", "-o", type=click.Path(), default="-")
def kml(output: str) -> None:
    """Export to KML (Google Earth / Maps)."""
    m = _load_mission()
    if not m.waypoints():
        click.echo("  Error: mission is empty", err=True)
        sys.exit(1)
    content = m.to_kml()
    _write_output(output, content)
    if output != "-":
        click.echo(f"  Exported KML to {output}")


@export.command()
@click.option("--output", "-o", type=click.Path(), default="-")
def mavlink(output: str) -> None:
    """Export to MAVLink waypoint file (QGC / MP format)."""
    m = _load_mission()
    if not m.waypoints():
        click.echo("  Error: mission is empty", err=True)
        sys.exit(1)
    content = m.to_mavlink()
    _write_output(output, content)
    if output != "-":
        click.echo(f"  Exported MAVLink to {output}")


@export.command()
@click.option("--output", "-o", type=click.Path(), default="-")
def csv(output: str) -> None:
    """Export to CSV."""
    m = _load_mission()
    if not m.waypoints():
        click.echo("  Error: mission is empty", err=True)
        sys.exit(1)
    content = m.to_csv()
    _write_output(output, content)
    if output != "-":
        click.echo(f"  Exported CSV to {output}")


@export.command()
@click.option("--output", "-o", type=click.Path(), default="-")
def plan(output: str) -> None:
    """Export to QGroundControl .plan (JSON)."""
    m = _load_mission()
    if not m.waypoints():
        click.echo("  Error: mission is empty", err=True)
        sys.exit(1)
    if output == "-" or output == "stdout":
        click.echo(json.dumps(to_qgc_plan(m), indent=2))
    else:
        save_qgc_plan(m, output)
        click.echo(f"  Exported QGC .plan to {output}")


@export.command("wpl")
@click.option("--output", "-o", type=click.Path(), default="-")
def wpl(output: str) -> None:
    """Export to QGC WPL text (QGroundControl / Mission Planner)."""
    m = _load_mission()
    if not m.waypoints():
        click.echo("  Error: mission is empty", err=True)
        sys.exit(1)
    content = to_wpl(m)
    _write_output(output, content)
    if output != "-":
        click.echo(f"  Exported WPL to {output}")


def _write_output(path: str, content: str) -> None:
    if path == "-" or path == "stdout":
        click.echo(content)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")


# ------------------------------------------------------------------
# generate group
# ------------------------------------------------------------------
@click.group()
def generate() -> None:
    """Generate automated mission patterns."""
    pass


@generate.command()
@click.option("--corner1", required=True, help="First corner: lat,lon  (e.g. 31.23,121.47)")
@click.option("--corner2", required=True, help="Opposite corner: lat,lon")
@click.option("--alt", "altitude", type=float, required=True, help="Survey altitude in metres")
@click.option("--speed", type=float, default=10.0, help="Speed in m/s")
@click.option("--spacing", "lane_spacing", type=float, default=20.0, help="Lane spacing in metres")
@click.option("--corner", "start_corner",
              type=click.Choice(["nw", "ne", "sw", "se"], case_sensitive=False),
              default="nw", help="Start corner (north-west by default)")
@click.option("--from-outer/--from-inner", "start_from_outer", default=True,
              help="Start from outer edge (default: outer)")
@click.option("--save/--no-save", "auto_save", default=True)
def lawnmower(corner1, corner2, altitude, speed, lane_spacing, start_corner, start_from_outer, auto_save) -> None:
    """Generate a rectangular lawn-mower (survey) pattern.

    Example: --corner1 31.230,121.470 --corner2 31.235,121.480 --alt 50
    """
    lat1, lon1 = _parse_latlon(corner1)
    lat2, lon2 = _parse_latlon(corner2)
    params = LawnMowerParams(
        corner1=(lat1, lon1),
        corner2=(lat2, lon2),
        altitude=altitude,
        speed=speed,
        lane_spacing=lane_spacing,
        start_corner=StartCorner.from_str(start_corner),
        start_from_outer=start_from_outer,
    )
    errors = params.validate()
    if errors:
        click.echo("  Validation errors:", err=True)
        for e in errors:
            click.echo(f"    - {e}", err=True)
        sys.exit(1)

    mission = Mission(name="Lawn-Mower Survey")
    for wp in generate_lawnmower(params):
        mission.add_waypoint(**wp.to_dict())

    if auto_save:
        _save_mission(mission)

    click.echo(f"  Generated {len(mission)} waypoints (lawn-mower pattern)")
    click.echo(f"  Total distance: {mission.total_distance()/1000:.2f} km")
    click.echo(f"  Est. duration: ~{int(mission.estimated_duration()/60)}m")
    if auto_save:
        click.echo(f"  Saved to default mission.")


@generate.command()
@click.option("--polygon", required=True, multiple=True,
              help="Polygon vertex: lat,lon  (specify 3+ times)")
@click.option("--alt", "altitude", type=float, required=True, help="Survey altitude in metres")
@click.option("--speed", type=float, default=10.0, help="Speed in m/s")
@click.option("--spacing", "lane_spacing", type=float, default=20.0, help="Lane spacing in metres")
@click.option("--angle", "sweep_angle_deg", type=float, default=0.0,
              help="Sweep angle in degrees (0=NS lanes)")
@click.option("--from-outer/--from-inner", "start_from_outer", default=True)
@click.option("--save/--no-save", "auto_save", default=True)
def polygon(polygon, altitude, speed, lane_spacing, sweep_angle_deg, start_from_outer, auto_save) -> None:
    """Generate a lawn-mower scan within a polygon area.

    Provide at least 3 --polygon vertices. Example:
      mavplan generate polygon --polygon 31.230,121.470 --polygon 31.240,121.470 \\
             --polygon 31.240,121.480 --polygon 31.230,121.480 --alt 50
    """
    if len(polygon) < 3:
        click.echo("  Error: polygon requires at least 3 vertices", err=True)
        sys.exit(1)
    verts = [_parse_latlon(p) for p in polygon]
    params = PolygonScanParams(
        polygon=[(lat, lon) for lat, lon in verts],
        altitude=altitude,
        speed=speed,
        lane_spacing=lane_spacing,
        sweep_angle_deg=sweep_angle_deg,
        start_from_outer=start_from_outer,
    )
    errors = params.validate()
    if errors:
        click.echo("  Validation errors:", err=True)
        for e in errors:
            click.echo(f"    - {e}", err=True)
        sys.exit(1)

    mission = Mission(name="Polygon Survey")
    for wp in generate_polygon_scan(params):
        mission.add_waypoint(**wp.to_dict())

    if not mission.waypoints():
        click.echo("  Error: pattern produced no waypoints (polygon may be too small)", err=True)
        sys.exit(1)

    if auto_save:
        _save_mission(mission)

    click.echo(f"  Generated {len(mission)} waypoints (polygon scan)")
    click.echo(f"  Total distance: {mission.total_distance()/1000:.2f} km")
    if auto_save:
        click.echo(f"  Saved to default mission.")


@generate.command()
@click.option("--center", required=True, help="Orbit center: lat,lon  (e.g. 31.23,121.47)")
@click.option("--radius", type=float, required=True, help="Orbit radius in metres")
@click.option("--alt", "altitude", type=float, required=True, help="Orbit altitude in metres")
@click.option("--speed", type=float, default=10.0, help="Speed in m/s")
@click.option("--points", "num_points", type=int, default=12, help="Number of waypoints")
@click.option("--direction", type=click.Choice(["cw", "ccw"]), default="ccw", help="Orbit direction")
@click.option("--save/--no-save", "auto_save", default=True)
def orbit(center, radius, altitude, speed, num_points, direction, auto_save) -> None:
    """Generate a circular orbit / loiter pattern.

    Example: --center 31.23,121.47 --radius 50 --alt 50 --points 12
    """
    lat, lon = _parse_latlon(center)
    params = OrbitParams(
        center_lat=lat,
        center_lon=lon,
        radius=radius,
        altitude=altitude,
        speed=speed,
        num_points=num_points,
        direction=direction,
    )
    errors = params.validate()
    if errors:
        click.echo("  Validation errors:", err=True)
        for e in errors:
            click.echo(f"    - {e}", err=True)
        sys.exit(1)

    mission = Mission(name=f"Orbit r={radius}m")
    for wp in generate_orbit(params):
        mission.add_waypoint(**wp.to_dict())

    if auto_save:
        _save_mission(mission)

    click.echo(f"  Generated {len(mission)} waypoints (orbit)")
    click.echo(f"  Orbit circumference: {2*3.14159*radius:.0f}m")
    if auto_save:
        click.echo(f"  Saved to default mission.")


def _parse_latlon(s: str) -> tuple[float, float]:
    """Parse 'lat,lon' string into (lat, lon) tuple."""
    parts = s.split(",")
    if len(parts) != 2:
        raise click.BadParameter(f"Expected 'lat,lon', got: {s}")
    try:
        lat = float(parts[0].strip())
        lon = float(parts[1].strip())
    except ValueError:
        raise click.BadParameter(f"Invalid number in: {s}")
    return lat, lon


# ------------------------------------------------------------------
# analyze group
# ------------------------------------------------------------------
@click.group()
def analyze() -> None:
    """Analyze flight logs and compare to planned missions."""
    pass


@analyze.command()
@click.argument("csv_path", type=click.Path(exists=True))
def log(csv_path: str) -> None:
    """Analyze a CSV flight log and print statistics.

    Supported formats:
      - QGroundControl CSV exports
      - Mission Planner CSV exports
      - Generic GPS CSV (must contain lat/lon columns)

    Example: mavplan analyze log flight_log.csv
    """
    try:
        fl = parse_csv(csv_path)
    except Exception as e:
        click.echo(f"  Error parsing {csv_path}: {e}", err=True)
        sys.exit(1)

    stats = fl.stats()
    click.echo(f"  Source: {fl.source_file}")
    click.echo(f"  Points: {stats.num_points}")
    click.echo("")
    click.echo(f"  Distance:")
    click.echo(f"    Total path: {stats.total_distance_m/1000:.2f} km")
    click.echo(f"    Straight line: {stats.horizontal_distance_m/1000:.2f} km")
    click.echo("")
    click.echo(f"  Altitude:")
    click.echo(f"    Min: {stats.min_altitude_m:.1f} m")
    click.echo(f"    Max: {stats.max_altitude_m:.1f} m")
    click.echo(f"    Range: {stats.max_altitude_change_m:.1f} m")
    click.echo("")
    click.echo(f"  Speed:")
    click.echo(f"    Avg: {stats.avg_speed_mps:.1f} m/s ({stats.avg_speed_mps*3.6:.1f} km/h)")
    click.echo(f"    Max: {stats.max_speed_mps:.1f} m/s ({stats.max_speed_mps*3.6:.1f} km/h)")
    click.echo("")
    dur = stats.flight_duration_s
    if dur >= 3600:
        dur_str = f"{int(dur//3600)}h {int((dur%3600)//60)}m {int(dur%60)}s"
    elif dur >= 60:
        dur_str = f"{int(dur//60)}m {int(dur%60)}s"
    else:
        dur_str = f"{dur:.1f}s"
    click.echo(f"  Duration: {dur_str}")
    click.echo("")
    click.echo(f"  Start: {stats.start_lat:.7f}, {stats.start_lon:.7f}")
    click.echo(f"  End:   {stats.end_lat:.7f}, {stats.end_lon:.7f}")


@analyze.command()
@click.argument("csv_path", type=click.Path(exists=True))
@click.argument("plan_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="", help="KML output path")
def compare(csv_path: str, plan_path: str, output: str) -> None:
    """Compare a flight log against a planned mission.

    Outputs coverage statistics and optionally writes a KML overlay
    with both the planned route (green) and actual flight path (blue).

    Example:
      mavplan analyze compare flight.csv plan.json -o comparison.kml
    """
    try:
        fl = parse_csv(csv_path)
    except Exception as e:
        click.echo(f"  Error parsing flight log {csv_path}: {e}", err=True)
        sys.exit(1)

    try:
        plan = Mission.load(plan_path)
    except Exception as e:
        click.echo(f"  Error loading plan {plan_path}: {e}", err=True)
        sys.exit(1)

    result = compare_to_plan(fl, plan)
    if "error" in result:
        click.echo(f"  Error: {result['error']}", err=True)
        sys.exit(1)

    click.echo(f"  Mission: {plan.name}")
    click.echo(f"  Flight log: {fl.source_file}")
    click.echo("")
    click.echo(f"  Distance:")
    click.echo(f"    Planned: {result['plan_distance_m']/1000:.2f} km")
    click.echo(f"    Flown:   {result['flight_distance_m']/1000:.2f} km")
    click.echo(f"    Coverage: {result['coverage_ratio']:.0%}")
    click.echo("")
    click.echo(f"  Waypoint hit rate:")
    click.echo(f"    Within 10m: {result['waypoint_hits_10m']}/{result['total_plan_waypoints']}")
    click.echo(f"    Within 20m: {result['waypoint_hits_20m']}/{result['total_plan_waypoints']}")
    click.echo(f"    Within 50m: {result['waypoint_hits_50m']}/{result['total_plan_waypoints']}")
    click.echo("")
    click.echo(f"  Altitude:")
    click.echo(f"    Avg deviation: {result['avg_altitude_error_m']:.1f} m")

    if output:
        stats = fl.stats()
        plan_kml = plan.to_kml().replace(
            "ff0000ff", "ff00ff00")  # green for plan
        flight_kml = fl.to_kml(color="ff0000ff")  # blue for flight
        combined = _merge_kml(plan_kml, flight_kml, plan.name)
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(combined, encoding="utf-8")
        click.echo(f"")
        click.echo(f"  KML saved to {output}")
        click.echo("  Green=planned route  Blue=actual flight")


@analyze.command()
@click.argument("csv_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="", help="KML output path")
def kml(csv_path: str, output: str) -> None:
    """Export a CSV flight log as KML.

    Example: mavplan analyze kml flight.csv -o flight.kml
    """
    try:
        fl = parse_csv(csv_path)
    except Exception as e:
        click.echo(f"  Error parsing {csv_path}: {e}", err=True)
        sys.exit(1)

    kml_content = fl.to_kml(name="Flight Log - " + Path(csv_path).stem)
    if not output or output == "-":
        click.echo(kml_content)
    else:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(kml_content, encoding="utf-8")
        click.echo(f"  KML saved to {output} ({len(fl)} points)")


def _merge_kml(plan_kml: str, flight_kml: str, mission_name: str) -> str:
    """Merge two KML documents into one with both paths."""
    # Extract Document content from each KML
    def extract_body(kml_str: str) -> str:
        start = kml_str.find("<Document>")
        end = kml_str.find("</Document>")
        if start == -1 or end == -1:
            return ""
        return kml_str[start + len("<Document>"):end]

    plan_body = extract_body(plan_kml)
    flight_body = extract_body(flight_kml)

    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{mission_name} - Planned vs Actual</name>
    <description>Green = planned route | Blue = actual flight</description>
    <Style id="plan_track">
      <LineStyle><color>ff00ff00</color><width>4</width></LineStyle>
    </Style>
    <Style id="flight_track">
      <LineStyle><color>ff0000ff</color><width>3</width></LineStyle>
    </Style>
{plan_body}
{flight_body}
  </Document>
</kml>
"""


# ------------------------------------------------------------------
# template group
# ------------------------------------------------------------------
@click.group()
def template() -> None:
    """Mission template library."""
    pass


@template.command("list")
def tmpl_list() -> None:
    """List all built-in mission templates."""
    list_templates()


@template.command("export")
@click.argument("output_path", type=click.Path())
def tmpl_export(output_path: str) -> None:
    """Export the template library as JSON.

    Example: mavplan template export templates.json
    """
    save_templates_library(output_path)
    click.echo(f"  Saved {len(get_templates())} templates to {output_path}")


@template.command("load")
@click.argument("name")
@click.option("--output", "-o", type=click.Path(), default="", help="Mission output path")
def tmpl_load(name: str, output: str) -> None:
    """Load a template and optionally save as a mission file.

    Example: mavplan template load "Large Area Survey" -o mission.json
    """
    templates = get_templates()
    matched = [t for t in templates if name.lower() in t.name.lower()]
    if not matched:
        click.echo(f"  Template not found: {name}", err=True)
        click.echo(f"  Run 'mavplan template list' to see available templates")
        sys.exit(1)

    t = matched[0]
    click.echo(f"  Template: {t.name}")
    click.echo(f"  Description: {t.description}")
    click.echo(f"  Category: {t.category}")
    click.echo(f"  Waypoints: {len(t.mission)}")
    click.echo(f"  Total distance: {t.mission.total_distance()/1000:.2f} km")
    click.echo(f"  Est. duration: ~{int(t.mission.estimated_duration()/60)}m")

    if output:
        t.mission.save(output)
        click.echo(f"  Saved to {output}")


@template.command("import-kml")
@click.argument("kml_path", type=click.Path(exists=True))
@click.option("--alt", "default_alt", type=float, default=50.0, help="Default altitude in metres")
@click.option("--speed", type=float, default=10.0, help="Default speed in m/s")
@click.option("--output", "-o", type=click.Path(), default="", help="Mission output path")
def tmpl_import_kml(kml_path: str, default_alt: float, speed: float, output: str) -> None:
    """Import a KML file as a mission.

    Parses KML Placemarks (Point, LineString, Polygon) and converts
    coordinates to waypoints.

    Example: mavplan template import-kml site.kml --alt 60 -o mission.json
    """
    try:
        doc = parse_kml(kml_path)
    except Exception as e:
        click.echo(f"  Error parsing KML: {e}", err=True)
        sys.exit(1)

    if not doc.waypoints:
        click.echo(f"  No waypoints found in KML", err=True)
        sys.exit(1)

    mission = doc.to_mission(default_alt=default_alt, default_speed=speed)
    click.echo(f"  Imported {len(mission)} waypoints from KML")
    click.echo(f"  KML name: {doc.name or '(unnamed)'}")
    click.echo(f"  Total distance: {mission.total_distance()/1000:.2f} km")

    if output:
        mission.save(output)
        click.echo(f"  Saved to {output}")


# ------------------------------------------------------------------
# link group (MAVLink connection)
# ------------------------------------------------------------------
@click.group()
def link() -> None:
    """Connect to autopilot via MAVLink and upload/download missions.

    Requires pymavlink: pip install pymavlink
    """
    pass


@link.command("status")
@click.argument("device", default="udp:127.0.0.1:14550")
def link_status(device: str) -> None:
    """Show autopilot connection status.

    Example: mavplan link status udp:127.0.0.1:14550
             mavplan link status serial:COM3:57600
    """
    try:
        conn = MAVLinkConnection.connect(device)
    except ImportError:
        click.echo("  Error: pymavlink not installed", err=True)
        click.echo("  Install with: pip install pymavlink", err=True)
        sys.exit(1)
    except ConnectionError as e:
        click.echo(f"  Connection failed: {e}", err=True)
        sys.exit(1)

    hb = conn.last_heartbeat
    click.echo(f"  Connected to {device}")
    click.echo(f"  State: {conn.state.value}")
    click.echo(f"  Autopilot: {hb.autopilot_type}")
    click.echo(f"  Type: {hb.system_type}")
    click.echo(f"  Status: {hb.system_status}")
    click.echo(f"  Armed: {hb.armed}")
    click.echo(f"  Mode: AUTO" if hb.auto_mode else "  Mode: MANUAL")
    conn.close()


@link.command("upload")
@click.argument("device", default="udp:127.0.0.1:14550")
@click.argument("mission_path", type=click.Path(exists=True))
def link_upload(device: str, mission_path: str) -> None:
    """Upload a mission to the autopilot.

    Example: mavplan link upload udp:127.0.0.1:14550 mission.json
             mavplan link upload serial:COM3:57600 survey.json
    """
    try:
        conn = MAVLinkConnection.connect(device)
    except ImportError:
        click.echo("  Error: pymavlink not installed", err=True)
        click.echo("  Install with: pip install pymavlink", err=True)
        sys.exit(1)
    except ConnectionError as e:
        click.echo(f"  Connection failed: {e}", err=True)
        sys.exit(1)

    try:
        mission = Mission.load(mission_path)
    except Exception as e:
        click.echo(f"  Error loading mission: {e}", err=True)
        conn.close()
        sys.exit(1)

    click.echo(f"  Uploading '{mission.name}' ({len(mission)} waypoints)...")
    result = conn.upload_mission(mission)
    if result["success"]:
        click.echo(f"  OK: {result['message']}")
    else:
        click.echo(f"  FAILED: {result['message']}", err=True)
    conn.close()


@link.command("download")
@click.argument("device", default="udp:127.0.0.1:14550")
@click.argument("output_path", type=click.Path())
def link_download(device: str, output_path: str) -> None:
    """Download the current mission from the autopilot.

    Example: mavplan link download udp:127.0.0.1:14550 downloaded.json
    """
    try:
        conn = MAVLinkConnection.connect(device)
    except ImportError:
        click.echo("  Error: pymavlink not installed", err=True)
        click.echo("  Install with: pip install pymavlink", err=True)
        sys.exit(1)
    except ConnectionError as e:
        click.echo(f"  Connection failed: {e}", err=True)
        sys.exit(1)

    click.echo(f"  Downloading mission from autopilot...")
    success, result = conn.download_mission()
    if not success:
        click.echo(f"  FAILED: {result}", err=True)
        conn.close()
        sys.exit(1)

    mission = Mission(name="Downloaded Mission")
    for wp in result:
        mission.add_waypoint(lat=wp.lat, lon=wp.lon, alt=wp.alt,
                             speed=wp.speed, delay=wp.delay, yaw=wp.yaw)

    mission.save(output_path)
    click.echo(f"  Downloaded {len(mission)} waypoints -> {output_path}")
    conn.close()


# ------------------------------------------------------------------
# simulate group
# ------------------------------------------------------------------
@click.group()
def simulate() -> None:
    """Simulate mission: battery, time, wind, safety checks."""
    pass


@simulate.command(name="run")
@click.argument("mission_path", type=click.Path(exists=True))
@click.option("--capacity", "cap_mah", type=float, default=5000.0, help="Battery capacity in mAh")
@click.option("--voltage", type=float, default=22.2, help="Battery nominal voltage (V)")
@click.option("--wind", "wind_speed", type=float, default=0.0, help="Wind speed in m/s")
@click.option("--wind-dir", "wind_dir", type=click.Choice(["none", "headwind", "tailwind", "crosswind"]),
              default="none", help="Wind direction relative to travel")
@click.option("--reserve", type=float, default=20.0, help="Battery reserve percent to keep")
def sim_run(mission_path, cap_mah, voltage, wind_speed, wind_dir, reserve) -> None:
    """Run a mission simulation.

    Example: mavplan simulate run mission.json --capacity 8000 --wind 5 --wind-dir headwind
    """
    try:
        mission = Mission.load(mission_path)
    except Exception as e:
        click.echo(f"  Error loading mission: {e}", err=True)
        sys.exit(1)

    battery = BatteryModel(capacity_mah=cap_mah, voltage=voltage)
    wind_map = {
        "none": WindDirection.NONE,
        "headwind": WindDirection.HEADWIND,
        "tailwind": WindDirection.TAILWIND,
        "crosswind": WindDirection.CROSSWIND,
    }
    wind = WindModel(speed_ms=wind_speed, direction=wind_map[wind_dir])
    params = SimulationParams(battery=battery, wind=wind, reserve_percent=reserve)

    report = generate_report(mission, params)
    click.echo(report)


@simulate.command(name="battery")
@click.argument("mission_path", type=click.Path(exists=True))
@click.option("--capacity", "cap_mah", type=float, default=5000.0, help="Battery capacity in mAh")
@click.option("--voltage", type=float, default=22.2, help="Battery nominal voltage (V)")
def sim_battery(mission_path, cap_mah, voltage) -> None:
    """Estimate battery consumption only.

    Example: mavplan simulate battery mission.json --capacity 8000
    """
    try:
        mission = Mission.load(mission_path)
    except Exception as e:
        click.echo(f"  Error loading mission: {e}", err=True)
        sys.exit(1)

    battery = BatteryModel(capacity_mah=cap_mah, voltage=voltage)
    params = SimulationParams(battery=battery)
    result = estimate_energy(mission, params)

    click.echo(f"  Energy used: {result.energy_consumed_wh:.1f} Wh")
    click.echo(f"  Battery capacity: {battery.capacity_wh:.1f} Wh")
    click.echo(f"  Used: {result.battery_used_percent:.0f}%")
    click.echo(f"  Remaining: {result.battery_remaining_percent:.0f}%")
    click.echo(f"  Feasible: {result.feasible}")


@simulate.command(name="geofence")
@click.argument("mission_path", type=click.Path(exists=True))
@click.option("--max-range", "max_range", type=float, default=500.0, help="Max range from home in metres")
def sim_geofence(mission_path, max_range) -> None:
    """Check geofence compliance.

    Example: mavplan simulate geofence mission.json --max-range 1000
    """
    try:
        mission = Mission.load(mission_path)
    except Exception as e:
        click.echo(f"  Error loading mission: {e}", err=True)
        sys.exit(1)

    warnings = check_geofence(mission, max_range)
    if warnings:
        click.echo(f"  Geofence violations ({max_range/1000:.1f}km limit):")
        for w in warnings:
            click.echo(f"    - {w}")
        sys.exit(1)
    else:
        click.echo(f"  OK: all waypoints within {max_range/1000:.1f}km geofence")


@simulate.command(name="with-tol")
@click.argument("mission_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="", help="Output mission path")
def sim_with_tol(mission_path, output) -> None:
    """Insert takeoff and landing waypoints.

    Example: mavplan simulate with-tol mission.json -o mission_with_tol.json
    """
    try:
        mission = Mission.load(mission_path)
    except Exception as e:
        click.echo(f"  Error loading mission: {e}", err=True)
        sys.exit(1)

    params = SimulationParams()
    new_mission = insert_takeoff_landing(mission, params)
    click.echo(f"  Added takeoff/landing: {len(mission)} -> {len(new_mission)} waypoints")

    if output:
        new_mission.save(output)
        click.echo(f"  Saved to {output}")


# ------------------------------------------------------------------
# root
# ------------------------------------------------------------------
@click.group()
def main() -> None:
    """mavplan — MAVLink mission planner CLI.

    Quick start:
      mavplan waypoint add --lat 31.23 --lon 121.47 --alt 50
      mavplan waypoint add --lat 31.24 --lon 121.48 --alt 50
      mavplan export kml -o mission.kml
    """
    pass


main.add_command(waypoint)
main.add_command(mission)
main.add_command(export)
main.add_command(generate)
main.add_command(analyze)
main.add_command(template)
main.add_command(link)
main.add_command(simulate)


if __name__ == "__main__":
    main()
