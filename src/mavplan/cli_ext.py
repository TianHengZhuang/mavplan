"""CLI extensions: fleet, regional NFZ catalogue, one-click mission review."""
from __future__ import annotations

import json
from pathlib import Path

import click

from .admin_div import builtin_admin_index, load_admin_index
from .fleet import Drone, Fleet, assign_formation_offsets
from .mission import Mission
from .mission_review import ReviewContext, build_mission_review, render_review_markdown
from .nofly import load_zones_json
from .nfz_pack import (
    NfzPack,
    load_nfz_pack,
    records_to_zones,
    resolve_region_zones,
    save_nfz_pack,
)


@click.group()
def fleet() -> None:
    """Multi-drone fleet helpers (teaching)."""


@fleet.command("init")
@click.argument("mission", required=False)
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=Path("fleet.json"))
@click.option("--name", "fleet_name", default=None, help="Fleet mission name override")
def fleet_init(mission: str | None, out_path: Path, fleet_name: str | None) -> None:
    """Create a single-lead fleet JSON (optionally from a mission file)."""
    name = fleet_name or "Untitled Mission"
    home = None
    if mission:
        m = Mission.load(mission)
        name = fleet_name or m.name
        wps = m.waypoints()
        if wps:
            home = [wps[0].lat, wps[0].lon, 0.0]
    fl = Fleet.single_from_mission(name, home=home)
    out_path.write_text(json.dumps(fl.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    click.echo(f"Wrote {out_path} ({fl.count} drone)")


@fleet.command("add")
@click.argument("fleet_json", type=click.Path(exists=True, path_type=Path))
@click.option("--name", required=True)
@click.option("--callsign", default="")
@click.option("--model", default="")
@click.option("--role", type=click.Choice(["lead", "wingman", "standby"]), default="wingman")
@click.option("--airframe", type=click.Choice(["multirotor", "fixedwing", "vtol"]), default="multirotor")
@click.option("--battery-wh", type=float, default=77.0)
@click.option("--max-alt-m", type=float, default=120.0)
@click.option("--cruise-speed", type=float, default=10.0)
def fleet_add(
    fleet_json: Path,
    name: str,
    callsign: str,
    model: str,
    role: str,
    airframe: str,
    battery_wh: float,
    max_alt_m: float,
    cruise_speed: float,
) -> None:
    """Add a drone to an existing fleet JSON."""
    data = json.loads(fleet_json.read_text(encoding="utf-8"))
    fl = Fleet.from_dict(data)
    n = fl.count + 1
    fl.add(
        Drone(
            id=f"uav-{n}",
            name=name,
            callsign=callsign or f"UAV-{n:02d}",
            model=model,
            role=role,  # type: ignore[arg-type]
            airframe=airframe,  # type: ignore[arg-type]
            battery_wh=battery_wh,
            max_alt_m=max_alt_m,
            cruise_speed_ms=cruise_speed,
        )
    )
    fleet_json.write_text(json.dumps(fl.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    click.echo(f"Fleet now has {fl.count} drones")


@fleet.command("show")
@click.argument("fleet_json", type=click.Path(exists=True, path_type=Path))
@click.option("--spacing-m", type=float, default=30.0)
def fleet_show(fleet_json: Path, spacing_m: float) -> None:
    """Print fleet summary and formation offsets."""
    fl = Fleet.from_dict(json.loads(fleet_json.read_text(encoding="utf-8")))
    click.echo(f"Mission: {fl.mission_name}")
    click.echo(f"Drones:  {fl.count}")
    for d in fl.drones:
        click.echo(f"  - {d.name} [{d.callsign}] {d.role} {d.status} {d.model}")
    for off in assign_formation_offsets(fl, spacing_m=spacing_m):
        click.echo(f"  offset {off['name']}: {off['offset_east_m']:.0f} m east (slot {off['slot']})")


@click.group()
def nfz() -> None:
    """Regional no-fly zone catalogue (province / city / district)."""


@nfz.command("provinces")
@click.option("--index", "index_path", type=click.Path(exists=True, path_type=Path), default=None)
def nfz_provinces(index_path: Path | None) -> None:
    index = load_admin_index(index_path) if index_path else builtin_admin_index()
    for p in index.provinces:
        click.echo(f"{p.code}  {p.name}")


@nfz.command("cities")
@click.argument("province")
@click.option("--index", "index_path", type=click.Path(exists=True, path_type=Path), default=None)
def nfz_cities(province: str, index_path: Path | None) -> None:
    index = load_admin_index(index_path) if index_path else builtin_admin_index()
    p = index.find_province(province)
    if not p:
        raise click.ClickException(f"unknown province: {province}")
    for c in p.cities:
        click.echo(f"{c.code}  {c.name}")


@nfz.command("list")
@click.argument("province")
@click.argument("city")
@click.option("--district", default=None)
@click.option("--packs", "packs_dir", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def nfz_list(province: str, city: str, district: str | None, packs_dir: Path | None, as_json: bool) -> None:
    """List no-fly zones for a region (defaults to the whole city)."""
    pack, records, warnings = resolve_region_zones(province, city, district, packs_dir=packs_dir)
    if as_json:
        click.echo(json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2))
    else:
        click.echo(f"{pack.province_name} / {pack.city_name}" + (f" / {district}" if district else ""))
        click.echo(f"source={pack.source} updated={pack.updated_at}")
        click.echo(pack.disclaimer)
        click.echo(f"zones: {len(records)}")
        for z in records:
            shape = f"r={z.radius_m:.0f}m" if z.kind == "circle" else f"poly({len(z.vertices)})"
            click.echo(f"  [{z.category}] {z.name}  {z.kind} {shape}  district={z.district or '-'}")
    for w in warnings:
        click.echo(f"warning: {w}")


@nfz.command("export-zones-json")
@click.argument("province")
@click.argument("city")
@click.option("--district", default=None)
@click.option("--packs", "packs_dir", type=click.Path(path_type=Path), default=None)
@click.option("-o", "--out", "out_path", type=click.Path(path_type=Path), required=True)
def nfz_export_zones_json(
    province: str, city: str, district: str | None, packs_dir: Path | None, out_path: Path
) -> None:
    """Export resolved zones in mavplan zones JSON layout."""
    _pack, records, _w = resolve_region_zones(province, city, district, packs_dir=packs_dir)
    zones = records_to_zones(records)
    payload = {"zones": [z.to_dict() for z in zones]}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    click.echo(f"Wrote {len(zones)} zones -> {out_path}")


@nfz.command("pack-show")
@click.argument("pack_json", type=click.Path(exists=True, path_type=Path))
def nfz_pack_show(pack_json: Path) -> None:
    pack = load_nfz_pack(pack_json)
    click.echo(f"{pack.province_name}/{pack.city_name} ({pack.city_code}) zones={len(pack.zones)}")
    click.echo(pack.disclaimer)


@click.command("review")
@click.argument("mission", type=click.Path(exists=True, path_type=Path))
@click.option("--fleet", "fleet_json", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--zones", "zones_json", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--nfz-region", nargs=2, type=str, default=None, help="PROVINCE CITY for builtin pack")
@click.option("--district", default=None)
@click.option("-o", "--out", "out_path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def review_cmd(
    mission: Path,
    fleet_json: Path | None,
    zones_json: Path | None,
    nfz_region: tuple[str, str] | None,
    district: str | None,
    out_path: Path | None,
    as_json: bool,
) -> None:
    """One-click pre / in-flight / post mission review."""
    m = Mission.load(mission)
    fl = Fleet.from_dict(json.loads(fleet_json.read_text(encoding="utf-8"))) if fleet_json else None
    zones = []
    if zones_json:
        zones = load_zones_json(zones_json)
    elif nfz_region:
        _pack, records, _w = resolve_region_zones(nfz_region[0], nfz_region[1], district)
        zones = records_to_zones(records)
    review = build_mission_review(ReviewContext(mission=m, fleet=fl, zones=zones))
    if as_json:
        text = json.dumps(review, ensure_ascii=False, indent=2)
    else:
        text = render_review_markdown(review)
    if out_path:
        out_path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")
        click.echo(f"Wrote {out_path}")
    else:
        click.echo(text)


def register(main: "object") -> None:
    """Attach extension commands to the root Click group."""
    main.add_command(fleet)
    main.add_command(nfz)
    main.add_command(review_cmd)
