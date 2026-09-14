"""China administrative division index (province / city / district).

Teaching-oriented subset with a stable JSON schema. Full national coverage
can be dropped in as a larger ``index.json`` without code changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class District:
    code: str
    name: str


@dataclass(frozen=True)
class City:
    code: str
    name: str
    districts: tuple[District, ...] = ()


@dataclass(frozen=True)
class Province:
    code: str
    name: str
    cities: tuple[City, ...] = ()


@dataclass
class AdminIndex:
    version: str = ""
    provinces: list[Province] = field(default_factory=list)

    def province_names(self) -> list[str]:
        return [p.name for p in self.provinces]

    def find_province(self, name_or_code: str) -> Optional[Province]:
        key = name_or_code.strip()
        for p in self.provinces:
            if p.code == key or p.name == key:
                return p
        return None

    def find_city(self, province: Province, name_or_code: str) -> Optional[City]:
        key = name_or_code.strip()
        for c in province.cities:
            if c.code == key or c.name == key:
                return c
        return None

    def find_district(self, city: City, name_or_code: str) -> Optional[District]:
        key = name_or_code.strip()
        for d in city.districts:
            if d.code == key or d.name == key:
                return d
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "provinces": [
                {
                    "code": p.code,
                    "name": p.name,
                    "cities": [
                        {
                            "code": c.code,
                            "name": c.name,
                            "districts": [{"code": d.code, "name": d.name} for d in c.districts],
                        }
                        for c in p.cities
                    ],
                }
                for p in self.provinces
            ],
        }


def _parse_city(raw: dict[str, Any]) -> City:
    districts = tuple(
        District(code=str(d.get("code") or ""), name=str(d.get("name") or ""))
        for d in (raw.get("districts") or [])
    )
    return City(code=str(raw.get("code") or ""), name=str(raw.get("name") or ""), districts=districts)


def parse_admin_index(data: dict[str, Any]) -> AdminIndex:
    provinces: list[Province] = []
    for praw in data.get("provinces") or []:
        cities = tuple(_parse_city(c) for c in (praw.get("cities") or []))
        provinces.append(
            Province(code=str(praw.get("code") or ""), name=str(praw.get("name") or ""), cities=cities)
        )
    return AdminIndex(version=str(data.get("version") or ""), provinces=provinces)


def load_admin_index(path: str | Path) -> AdminIndex:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return parse_admin_index(json.load(f))


# Built-in teaching seed (expand via index.json)
BUILTIN_ADMIN_INDEX: dict[str, Any] = {
    "version": "2026-09-teaching",
    "provinces": [
        {
            "code": "320000",
            "name": "江苏省",
            "cities": [
                {
                    "code": "320100",
                    "name": "南京市",
                    "districts": [
                        {"code": "320102", "name": "玄武区"},
                        {"code": "320106", "name": "鼓楼区"},
                        {"code": "320115", "name": "江宁区"},
                    ],
                },
                {
                    "code": "320300",
                    "name": "徐州市",
                    "districts": [
                        {"code": "320302", "name": "鼓楼区"},
                        {"code": "320303", "name": "云龙区"},
                        {"code": "320311", "name": "泉山区"},
                        {"code": "320312", "name": "铜山区"},
                    ],
                },
            ],
        },
        {
            "code": "310000",
            "name": "上海市",
            "cities": [
                {
                    "code": "310100",
                    "name": "上海市",
                    "districts": [
                        {"code": "310115", "name": "浦东新区"},
                        {"code": "310104", "name": "徐汇区"},
                    ],
                }
            ],
        },
    ],
}


def builtin_admin_index() -> AdminIndex:
    return parse_admin_index(BUILTIN_ADMIN_INDEX)
