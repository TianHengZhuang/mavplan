"""Regional no-fly zone packs (province/city/district catalogue).

Pack JSON is intentionally compatible with ``mavplan.nofly.load_zones_json``
zones plus catalogue metadata (``category``, ``district``, ``source``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .admin_div import AdminIndex, builtin_admin_index
from .taskspec import Zone


@dataclass
class NfzRecord:
    id: str
    name: str
    kind: str  # circle | polygon
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_m: Optional[float] = None
    ceiling_m: Optional[float] = None
    vertices: list[list[float]] = field(default_factory=list)
    category: str = "other"
    district: Optional[str] = None

    def to_zone(self) -> Zone:
        if self.kind == "circle":
            return Zone(
                name=self.name,
                lat=float(self.lat or 0.0),
                lon=float(self.lon or 0.0),
                radius_m=float(self.radius_m or 0.0),
                kind="circle",
            )
        ring = [(float(v[0]), float(v[1])) for v in self.vertices]
        return Zone(
            name=self.name,
            lat=ring[0][0] if ring else 0.0,
            lon=ring[0][1] if ring else 0.0,
            radius_m=float(self.radius_m or 0.0),
            kind="polygon",
            vertices=ring,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "lat": self.lat,
            "lon": self.lon,
            "radius_m": self.radius_m,
            "ceiling_m": self.ceiling_m,
            "vertices": self.vertices,
            "category": self.category,
            "district": self.district,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NfzRecord":
        vertices = []
        for v in data.get("vertices") or []:
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                vertices.append([float(v[0]), float(v[1])])
        return cls(
            id=str(data.get("id") or data.get("name") or "zone"),
            name=str(data.get("name") or "zone"),
            kind=str(data.get("kind") or "circle"),
            lat=float(data["lat"]) if data.get("lat") is not None else None,
            lon=float(data["lon"]) if data.get("lon") is not None else None,
            radius_m=float(data["radius_m"]) if data.get("radius_m") is not None else None,
            ceiling_m=float(data["ceiling_m"]) if data.get("ceiling_m") is not None else None,
            vertices=vertices,
            category=str(data.get("category") or "other"),
            district=str(data["district"]) if data.get("district") else None,
        )


@dataclass
class NfzPack:
    city_code: str
    city_name: str
    province_code: str = ""
    province_name: str = ""
    updated_at: str = ""
    source: str = "curated-teaching"
    disclaimer: str = (
        "教学演示数据，非法定航行资料；放飞前须以民航局 UOM / 空管公布为准。"
    )
    zones: list[NfzRecord] = field(default_factory=list)

    def filter_district(self, district: Optional[str]) -> list[NfzRecord]:
        if not district:
            return list(self.zones)
        key = district.strip()
        return [z for z in self.zones if (z.district or "") == key]

    def search(self, keyword: str) -> list[NfzRecord]:
        if not keyword:
            return list(self.zones)
        k = keyword.lower()
        return [
            z
            for z in self.zones
            if k in z.name.lower() or k in (z.category or "").lower()
        ]

    def to_zones(self, district: Optional[str] = None) -> list[Zone]:
        return [z.to_zone() for z in self.filter_district(district)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cityCode": self.city_code,
            "cityName": self.city_name,
            "provinceCode": self.province_code,
            "provinceName": self.province_name,
            "updatedAt": self.updated_at,
            "source": self.source,
            "disclaimer": self.disclaimer,
            "zones": [z.to_dict() for z in self.zones],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NfzPack":
        return cls(
            city_code=str(data.get("cityCode") or data.get("city_code") or ""),
            city_name=str(data.get("cityName") or data.get("city_name") or ""),
            province_code=str(data.get("provinceCode") or data.get("province_code") or ""),
            province_name=str(data.get("provinceName") or data.get("province_name") or ""),
            updated_at=str(data.get("updatedAt") or data.get("updated_at") or ""),
            source=str(data.get("source") or "curated-teaching"),
            disclaimer=str(data.get("disclaimer") or cls.disclaimer),
            zones=[NfzRecord.from_dict(z) for z in (data.get("zones") or [])],
        )


def load_nfz_pack(path: str | Path) -> NfzPack:
    with Path(path).open("r", encoding="utf-8") as f:
        return NfzPack.from_dict(json.load(f))


def save_nfz_pack(pack: NfzPack, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(pack.to_dict(), f, ensure_ascii=False, indent=2)
        f.write("\n")


# Built-in teaching pack: Xuzhou (Yunlong Lake demo)
BUILTIN_XUZHOU_PACK: dict[str, Any] = {
    "cityCode": "320300",
    "cityName": "徐州市",
    "provinceCode": "320000",
    "provinceName": "江苏省",
    "updatedAt": "2026-09-14",
    "source": "curated-teaching",
    "disclaimer": "教学演示数据，非法定航行资料；放飞前须以民航局 UOM / 空管公布为准。",
    "zones": [
        {
            "id": "xz-airport-01",
            "name": "徐州观音国际机场净空保护区",
            "kind": "circle",
            "lat": 34.059,
            "lon": 117.555,
            "radius_m": 10000,
            "ceiling_m": 600,
            "category": "airport",
            "district": None,
        },
        {
            "id": "xz-yunlong-demo",
            "name": "云龙湖景区教学演示禁飞圈",
            "kind": "circle",
            "lat": 34.2472,
            "lon": 117.1856,
            "radius_m": 300,
            "ceiling_m": 120,
            "category": "scenic",
            "district": "云龙区",
        },
        {
            "id": "xz-quanshan-demo",
            "name": "泉山教学缓冲区示例",
            "kind": "circle",
            "lat": 34.241,
            "lon": 117.178,
            "radius_m": 180,
            "ceiling_m": 100,
            "category": "training",
            "district": "泉山区",
        },
    ],
}


def builtin_pack_for_city(city_code: str) -> Optional[NfzPack]:
    if city_code == "320300":
        return NfzPack.from_dict(BUILTIN_XUZHOU_PACK)
    return None


def resolve_region_zones(
    province: str,
    city: str,
    district: Optional[str] = None,
    *,
    admin: Optional[AdminIndex] = None,
    packs_dir: Optional[str | Path] = None,
) -> tuple[NfzPack, list[NfzRecord], list[str]]:
    """Resolve province/city/district to a zone list.

    Returns (pack, records, warnings).
    """
    index = admin or builtin_admin_index()
    warnings: list[str] = []
    prov = index.find_province(province)
    if not prov:
        raise ValueError(f"unknown province: {province}")
    ct = index.find_city(prov, city)
    if not ct:
        raise ValueError(f"unknown city: {city} in {prov.name}")
    pack: Optional[NfzPack] = None
    if packs_dir:
        candidate = Path(packs_dir) / f"{ct.code}.json"
        if candidate.is_file():
            pack = load_nfz_pack(candidate)
    if pack is None:
        pack = builtin_pack_for_city(ct.code)
    if pack is None:
        pack = NfzPack(
            city_code=ct.code,
            city_name=ct.name,
            province_code=prov.code,
            province_name=prov.name,
            source="empty",
            zones=[],
        )
        warnings.append(f"no NFZ pack for {prov.name}/{ct.name}; list is empty")
    if district:
        if not index.find_district(ct, district):
            warnings.append(f"unknown district {district}; showing whole city")
            records = list(pack.zones)
        else:
            records = pack.filter_district(district)
    else:
        records = list(pack.zones)
    return pack, records, warnings


def records_to_zones(records: Iterable[NfzRecord]) -> list[Zone]:
    return [r.to_zone() for r in records]
