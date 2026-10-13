"""A scenario: the recipe for one simulation run, loaded from YAML.

The same scenario and seed always produce exactly the same data, so results can
be compared fairly between runs and code changes.
"""

from datetime import datetime, timedelta
from pathlib import Path

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from riskdetect.schema import to_utc
from riskdetect.synthetic.personas import PersonaName
from riskdetect.synthetic.platforms import PROFILES


class ScenarioError(ValueError):
    """A scenario file is missing or invalid."""


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    seed: int
    start: AwareDatetime
    duration_days: int = Field(ge=1, le=365)
    platforms: dict[str, int] = Field(min_length=1)  # platform name -> number of users
    persona_mix: dict[PersonaName, float] = Field(min_length=1)
    noise_rate: float = Field(default=0.001, ge=0.0, le=0.5)  # share of junk rows
    busy_days: int = Field(default=1, ge=0)  # days when everyone is twice as active

    @field_validator("start")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        return to_utc(value)

    @field_validator("platforms")
    @classmethod
    def _known_platforms(cls, value: dict[str, int]) -> dict[str, int]:
        unknown = set(value) - set(PROFILES)
        if unknown:
            raise ValueError(f"unknown platforms {sorted(unknown)}; known: {sorted(PROFILES)}")
        if any(count < 1 for count in value.values()):
            raise ValueError("each platform needs at least 1 user")
        return value

    @field_validator("persona_mix")
    @classmethod
    def _valid_mix(cls, value: dict[PersonaName, float]) -> dict[PersonaName, float]:
        if any(share < 0 for share in value.values()) or sum(value.values()) <= 0:
            raise ValueError("persona shares must be >= 0 and not all zero")
        return value

    @property
    def end(self) -> datetime:
        return self.start + timedelta(days=self.duration_days)


def load_scenario(path: Path) -> Scenario:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScenarioError(f"Scenario not found: {path}") from exc
    try:
        return Scenario.model_validate(data)
    except ValueError as exc:
        raise ScenarioError(f"Invalid scenario {path}:\n{exc}") from exc
