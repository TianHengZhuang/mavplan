"""Tests for scenario module (v1.6)."""
from __future__ import annotations

import pytest
from pathlib import Path

from mavplan.scenario import (
    ScenarioSpec,
    list_scenarios,
    load_scenario,
    materialise_mission,
    validate_scenario,
    default_scenarios_dir,
)
from mavplan.taskspec import TaskSpec, CheckPoint, Zone


SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


class TestListScenarios:
    def test_returns_list(self) -> None:
        scenarios = list_scenarios(scenarios_dir=SCENARIOS_DIR)
        assert isinstance(scenarios, list)

    def test_contains_all_eight(self) -> None:
        scenarios = list_scenarios(scenarios_dir=SCENARIOS_DIR)
        assert len(scenarios) == 8

    def test_sorted(self) -> None:
        scenarios = list_scenarios(scenarios_dir=SCENARIOS_DIR)
        assert scenarios == sorted(scenarios)

    def test_missing_dir_returns_empty(self) -> None:
        scenarios = list_scenarios(scenarios_dir=Path("/nonexistent/path"))
        assert scenarios == []

    def test_default_dir_exists(self) -> None:
        assert default_scenarios_dir().is_dir()


class TestLoadScenario:
    def test_loads_rectangle_patrol(self) -> None:
        spec = load_scenario("rectangle_patrol", scenarios_dir=SCENARIOS_DIR)
        assert spec.name == "rectangle_patrol"
        assert "巡检" in spec.title_zh
        assert spec.difficulty == "easy"
        assert len(spec.task.required) == 4
        assert len(spec.waypoints) == 5  # home + 4 waypoints in toml

    def test_loads_corridor_transit(self) -> None:
        spec = load_scenario("corridor_transit", scenarios_dir=SCENARIOS_DIR)
        assert spec.difficulty == "medium"
        assert len(spec.task.no_fly_zones) == 2
        assert spec.task.home[0] == 31.21

    def test_loads_search_rescue(self) -> None:
        spec = load_scenario("search_rescue", scenarios_dir=SCENARIOS_DIR)
        assert spec.difficulty == "hard"
        assert len(spec.task.required) == 3
        assert len(spec.task.no_fly_zones) == 1

    def test_missing_scenario_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_scenario("nonexistent_scenario", scenarios_dir=SCENARIOS_DIR)

    def test_task_validate_ok(self) -> None:
        for name in list_scenarios(scenarios_dir=SCENARIOS_DIR):
            spec = load_scenario(name, scenarios_dir=SCENARIOS_DIR)
            errs = spec.task.validate()
            assert errs == [], f"{name}: {errs}"

    def test_spec_title_bilingual(self) -> None:
        spec = load_scenario("rectangle_patrol", scenarios_dir=SCENARIOS_DIR)
        assert "巡检" in spec.title()
        assert "patrol" in spec.title(lang="en")

    def test_source_path_set(self) -> None:
        spec = load_scenario("rectangle_patrol", scenarios_dir=SCENARIOS_DIR)
        assert spec.source_path is not None
        assert spec.source_path.name == "rectangle_patrol.toml"


class TestMaterialiseMission:
    def test_returns_mission(self) -> None:
        from mavplan.mission import Mission

        spec = load_scenario("rectangle_patrol", scenarios_dir=SCENARIOS_DIR)
        mission = materialise_mission(spec)
        assert isinstance(mission, Mission)
        assert mission.name == "rectangle_patrol"

    def test_mission_has_waypoints(self) -> None:
        spec = load_scenario("rectangle_patrol", scenarios_dir=SCENARIOS_DIR)
        mission = materialise_mission(spec)
        wps = mission.waypoints()
        assert len(wps) >= 2

    def test_custom_name(self) -> None:
        spec = load_scenario("rectangle_patrol", scenarios_dir=SCENARIOS_DIR)
        mission = materialise_mission(spec, name="My Mission")
        assert mission.name == "My Mission"


class TestValidateScenario:
    def test_valid_scenarios(self) -> None:
        for name in list_scenarios(scenarios_dir=SCENARIOS_DIR):
            spec = load_scenario(name, scenarios_dir=SCENARIOS_DIR)
            errs = validate_scenario(spec)
            assert errs == [], f"{name}: {errs}"

    def test_invalid_task_raises(self) -> None:
        # A TaskSpec with bad coordinates should validate with errors.
        bad_task = TaskSpec(
            home=(-999, 121.0, 0.0),
        )
        spec = ScenarioSpec(
            name="test",
            title_zh="Test",
            title_en="Test",
            difficulty="easy",
            description="",
            task=bad_task,
        )
        errs = validate_scenario(spec)
        assert len(errs) > 0
