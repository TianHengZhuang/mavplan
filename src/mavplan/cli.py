"""Command-line interface for mavplan."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .mission import Mission
from .waypoint import Waypoint

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
    mission = _load_mission()
    wp = mission.add_waypoint(lat=lat, lon=lon, alt=alt, speed=speed, delay=delay, yaw=yaw)
    click.echo(f"  Added WP{wp.seq}: {lat:.7f}, {lon:.7f}, alt={alt:.1f}m")
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
        click.echo(
            f"  WP{wp.seq}: lat={wp.lat:.7f} lon={wp.lon:.7f} "
            f"alt={wp.alt:.1f}m speed={wp.speed:.0f}m/s "
            f"delay={wp.delay:.0f}s {yaw_str}"
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


def _write_output(path: str, content: str) -> None:
    if path == "-" or path == "stdout":
        click.echo(content)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")


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


if __name__ == "__main__":
    main()
