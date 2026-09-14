from __future__ import annotations

import pytest

from mavplan.admin_div import builtin_admin_index
from mavplan.fleet import Drone, Fleet, assign_formation_offsets, default_drone_name
from mavplan.mission import Mission
from mavplan.mission_review import ReviewContext, build_mission_review, render_review_markdown
from mavplan.nfz_pack import (
    BUILTIN_XUZHOU_PACK,
    NfzPack,
    builtin_pack_for_city,
    records_to_zones,
    resolve_region_zones,
)


def test_fleet_add_and_validate():
    fleet = Fleet.single_from_mission("江苏省徐州市 云龙湖", home=[34.2472, 117.1856, 0])
    assert fleet.count == 1
    assert fleet.lead() is not None
    fleet.add(
        Drone(id="uav-2", name="云龙二号", callsign="YLH-02", role="wingman")
    )
    assert fleet.count == 2
    assert fleet.validate() == []
    offsets = assign_formation_offsets(fleet, spacing_m=30)
    assert offsets[0]["slot"] == 0 or any(o["slot"] == 0 for o in offsets)
    assert any(o["offset_east_m"] != 0 for o in offsets)


def test_fleet_rejects_duplicate_name():
    fleet = Fleet.single_from_mission("T")
    with pytest.raises(ValueError):
        fleet.add(Drone(id="uav-2", name=fleet.drones[0].name))


def test_admin_index_xuzhou():
    index = builtin_admin_index()
    js = index.find_province("江苏省")
    assert js is not None
    xz = index.find_city(js, "徐州市")
    assert xz is not None
    assert index.find_district(xz, "云龙区") is not None


def test_nfz_pack_district_filter():
    pack = NfzPack.from_dict(BUILTIN_XUZHOU_PACK)
    yunlong = pack.filter_district("云龙区")
    assert yunlong
    assert all(z.district == "云龙区" for z in yunlong)
    zones = records_to_zones(pack.zones)
    assert zones
    assert zones[0].kind == "circle"


def test_resolve_region_zones_builtin():
    pack, records, warnings = resolve_region_zones("江苏省", "徐州市")
    assert pack.city_code == "320300"
    assert records
    assert pack, warnings is not None


def test_resolve_region_zones_district():
    pack, records, _ = resolve_region_zones("江苏省", "徐州市", "云龙区")
    assert records
    assert all((r.district or "云龙区") == "云龙区" for r in records)


def test_builtin_pack_for_city():
    assert builtin_pack_for_city("320300") is not None
    assert builtin_pack_for_city("999999") is None


def test_mission_review_three_sections():
    mission = Mission(name="江苏省徐州市 云龙湖", home=(34.2472, 117.1856, 0))
    mission.add_waypoint(lat=34.2472, lon=117.1856, alt=50, speed=8)
    mission.add_waypoint(lat=34.250, lon=117.1856, alt=50, speed=8)
    mission.add_waypoint(lat=34.250, lon=117.190, alt=40, speed=6)
    fleet = Fleet.single_from_mission(mission.name, home=[34.2472, 117.1856, 0])
    pack = NfzPack.from_dict(BUILTIN_XUZHOU_PACK)
    review = build_mission_review(
        ReviewContext(mission=mission, fleet=fleet, zones=records_to_zones(pack.zones))
    )
    assert review["schema"] == "mavplan.review/1"
    assert review["drone_count"] == 1
    assert review["verdict"] in ("pass", "conditional", "fail")
    titles = [s["title"] for s in review["sections"]]
    assert titles == ["任务前分析", "任务中分析", "任务后分析"]
    md = render_review_markdown(review)
    assert "任务前分析" in md
    assert mission.name in md
