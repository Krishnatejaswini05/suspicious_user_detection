from pathlib import Path
from typing import Any

import pytest
import yaml

from riskdetect.synthetic import (
    PersonaName,
    Scenario,
    ScenarioError,
    assign_personas,
    load_scenario,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def scenario_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "t",
        "seed": 1,
        "start": "2026-08-01T00:00:00Z",
        "duration_days": 3,
        "platforms": {"synthetic_forum": 10},
        "persona_mix": {"normal": 1.0},
    }
    data.update(overrides)
    return data


class TestScenario:
    def test_default_scenario_file_is_valid(self) -> None:
        scenario = load_scenario(PROJECT_ROOT / "configs" / "scenarios" / "basic_v1.yaml")
        assert scenario.seed == 42
        assert set(scenario.platforms) == {"synthetic_forum", "synthetic_chat", "synthetic_market"}
        assert (scenario.end - scenario.start).days == 28

    @pytest.mark.parametrize(
        "change",
        [
            {"platforms": {"synthetic_twitter": 10}},
            {"platforms": {"synthetic_forum": 0}},
            {"persona_mix": {"normal": -1.0}},
            {"persona_mix": {"villain": 1.0}},
            {"duration_days": 0},
            {"start": "2026-08-01T00:00:00"},  # no timezone
            {"noise_rate": 0.9},
            {"surprise": True},
        ],
    )
    def test_invalid(self, change: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            Scenario.model_validate(scenario_data(**change))

    def test_load_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ScenarioError, match="not found"):
            load_scenario(tmp_path / "missing.yaml")
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump(scenario_data(duration_days=0)), encoding="utf-8")
        with pytest.raises(ScenarioError, match="Invalid scenario"):
            load_scenario(bad)


class TestAssignPersonas:
    def test_counts_match_mix(self) -> None:
        mix = {PersonaName.NORMAL: 0.8, PersonaName.SPAM_BOT: 0.2}
        result = assign_personas(mix, 100)
        assert result.count(PersonaName.NORMAL) == 80
        assert result.count(PersonaName.SPAM_BOT) == 20

    def test_rounding_keeps_total(self) -> None:
        mix = {PersonaName.NORMAL: 1, PersonaName.LURKER: 1, PersonaName.POWER_USER: 1}
        assert len(assign_personas(mix, 10)) == 10

    def test_every_persona_appears_in_small_groups(self) -> None:
        mix = {PersonaName.NORMAL: 0.98, PersonaName.SPAM_BOT: 0.01, PersonaName.HIJACKED: 0.01}
        result = assign_personas(mix, 10)
        assert {PersonaName.SPAM_BOT, PersonaName.HIJACKED} <= set(result)
        assert len(result) == 10

    def test_zero_share_never_appears(self) -> None:
        mix = {PersonaName.NORMAL: 1.0, PersonaName.SPAM_BOT: 0.0}
        assert set(assign_personas(mix, 20)) == {PersonaName.NORMAL}
