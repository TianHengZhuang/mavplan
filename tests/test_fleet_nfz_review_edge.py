"""Edge-case / reasonableness QA for fleet, nfz_pack, mission_review."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mavplan.admin_div import BUILTIN_ADMIN_INDEX, builtin_admin_index, parse_admin_index
from mavplan.fleet import (
    Drone,
    Fleet,
    assign_formation_offsets,
    default_drone_name,
    next_drone_id,
    validate_drone,
)
from mavplan.mission import Mission
from mavplan.mission_review import (
    ReviewContext,
    build_in_flight_section,
    build_mission_review,
    build_pre_flight_section,
    render_review_markdown,
)
from mavplan.nfz_pack import (
    BUILTIN_XUZHOU_PACK,
    NfzPack,
    NfzRecord,
    builtin_pack_for_city,
    load_nfz_pack,
    records_to_zones,
    resolve_region_zones,
    save_nfz_pack,
)
from mavplan.taskspec import Zone


class TestFleetEdge:
    def test_empty_fleet_validate(self):
        fl = Fleet(mission_name="", drones=[])
        issues = fl.validate()
        assert any("mission_name" in i for i in issues)
        assert any("no drones" in i for i in issues)

    def test_two_leads_rejected_by_validate(self):
        fl = Fleet(
            mission_name="T",
            drones=[
                Drone(id="a", name="A", role="lead"),
                Drone(id="b", name="B", role="lead"),
            ],
        )
        assert any("more than one lead" in i for i in fl.validate())

    def test_add_second_lead_demotes_first(self):
        fl = Fleet.single_from_mission("T")
        fl.add(Drone(id="uav-2", name="僚机", role="lead"))
        leads = [d for d in fl.drones if d.role == "lead"]
        assert len(leads) == 1
        assert leads[0].id == "uav-2"

    def test_invalid_name_rejected(self):
        fl = Fleet.single_from_mission("T")
        with pytest.raises(ValueError):
            fl.add(Drone(id="x", name="bad name!"))

    def test_invalid_battery(self):
        issues = validate_drone(Drone(id="x", name="OK", battery_wh=0), existing=[])
        assert any("battery_wh" in i for i in issues)

    def test_from_dict_tolerates_garbage(self):
        fl = Fleet.from_dict({"mission_name": "X", "drones": [{"id": "u1", "name": "N"}]})
        assert fl.count == 1
        assert fl.drones[0].airframe == "multirotor"

    def test_remove_missing(self):
        fl = Fleet.single_from_mission("T")
        assert fl.remove("nope") is False
        assert fl.remove("uav-1") is True
        assert fl.count == 0

    def test_next_drone_id_collision(self):
        drones = [Drone(id="uav-1", name="A"), Drone(id="uav-2", name="B")]
        assert next_drone_id(drones) == "uav-3"

    def test_default_name(self):
        assert default_drone_name(3) == "UAV-3"

    def test_formation_offsets_spacing(self):
        fl = Fleet.single_from_mission("T")
        fl.add(Drone(id="uav-2", name="W1", role="wingman"))
        fl.add(Drone(id="uav-3", name="W2", role="wingman"))
        offs = assign_formation_offsets(fl, spacing_m=40)
        east = sorted(o["offset_east_m"] for o in offs)
        assert 0 in east
        assert any(abs(v) >= 40 for v in east)


class TestAdminNfzEdge:
    def test_unknown_province(self):
        with pytest.raises(ValueError):
            resolve_region_zones("不存在省", "徐州市")

    def test_unknown_city(self):
        with pytest.raises(ValueError):
            resolve_region_zones("江苏省", "不存在市")

    def test_unknown_district_warning(self):
        pack, records, warnings = resolve_region_zones("江苏省", "徐州市", "不存在区")
        assert any("unknown district" in w for w in warnings)
        assert pack.zones  # falls back to whole city

    def test_empty_pack_city(self):
        pack, records, warnings = resolve_region_zones("上海市", "上海市")
        assert pack.city_code == "310100"
        assert records == []
        assert any("no NFZ pack" in w for w in warnings)

    def test_polygon_record_to_zone(self):
        rec = NfzRecord(
            id="p1",
            name="多边形区",
            kind="polygon",
            vertices=[[34.2, 117.1], [34.21, 117.1], [34.21, 117.12], [34.2, 117.12]],
            radius_m=0,
        )
        z = rec.to_zone()
        assert z.kind == "polygon"
        assert len(z.polygon_ring()) == 4

    def test_circle_missing_coords(self):
        rec = NfzRecord(id="c", name="bad", kind="circle")
        z = rec.to_zone()
        assert z.radius_m == 0.0
        # validation should complain
        errs = z.validate()
        assert errs

    def test_pack_roundtrip(self, tmp_path: Path):
        pack = NfzPack.from_dict(BUILTIN_XUZHOU_PACK)
        p = tmp_path / "320300.json"
        save_nfz_pack(pack, p)
        again = load_nfz_pack(p)
        assert again.city_code == pack.city_code
        assert len(again.zones) == len(pack.zones)

    def test_search_keyword(self):
        pack = NfzPack.from_dict(BUILTIN_XUZHOU_PACK)
        hits = pack.search("机场")
        assert hits
        assert all("机场" in z.name for z in hits)

    def test_admin_index_parse_empty(self):
        idx = parse_admin_index({})
        assert idx.provinces == []
        assert idx.province_names() == []

    def test_builtin_has_xuzhou_districts(self):
        idx = builtin_admin_index()
        js = idx.find_province("320000")
        assert js is not None
        xz = idx.find_city(js, "320300")
        assert xz is not None
        assert idx.find_district(xz, "320303") is not None


class TestReviewEdge:
    def _mission(self, n=3):
        m = Mission(name="QA 任务", home=(34.2472, 117.1856, 0))
        m.add_waypoint(lat=34.2472, lon=117.1856, alt=50, speed=8)
        for i in range(1, n):
            m.add_waypoint(lat=34.2472 + 0.001 * i, lon=117.1856, alt=50, speed=8)
        return m

    def test_empty_mission_review(self):
        m = Mission(name="空任务")
        review = build_mission_review(ReviewContext(mission=m, fleet=None, zones=[]))
        assert review["verdict"] in ("pass", "conditional", "fail")
        assert len(review["sections"]) == 3
        md = render_review_markdown(review)
        assert "任务前分析" in md

    def test_single_waypoint_not_crash(self):
        m = Mission(name="单点")
        m.add_waypoint(lat=34.2, lon=117.1, alt=40, speed=5)
        mid = build_in_flight_section(m, None)
        assert mid["bullets"]

    def test_review_with_fleet_and_zone(self):
        m = self._mission()
        fl = Fleet.single_from_mission(m.name)
        fl.add(Drone(id="uav-2", name="僚机", role="wingman"))
        pack = NfzPack.from_dict(BUILTIN_XUZHOU_PACK)
        zones = records_to_zones(pack.zones)
        review = build_mission_review(ReviewContext(mission=m, fleet=fl, zones=zones))
        assert review["drone_count"] == 2
        assert isinstance(review["checks"], list)
        # markdown must include drone names
        md = render_review_markdown(review)
        assert "僚机" in md or "主机" in md

    def test_pre_section_verdict_fail_when_error(self):
        m = self._mission()
        # force an error-level check via fake list
        checks = [{"code": "no_fly_enter", "level": "error", "message": "进入禁飞区"}]
        pre = build_pre_flight_section(m, None, checks)
        assert pre["verdict"] == "fail"

    def test_nofly_enter_mentioned_post(self):
        m = self._mission()
        checks = [{"code": "no_fly_enter", "level": "error", "message": "x"}]
        from mavplan.mission_review import build_post_flight_section

        post = build_post_flight_section(m, None, checks)
        assert any("禁飞" in b for b in post["bullets"])


class TestCliExtImport:
    def test_register_callable(self):
        import click

        from mavplan import cli_ext

        @click.group()
        def root():
            pass

        cli_ext.register(root)
        cmds = sorted(root.commands.keys())
        assert "fleet" in cmds
        assert "nfz" in cmds
        assert "review" in cmds
