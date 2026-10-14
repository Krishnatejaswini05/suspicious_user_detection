"""Scoring settings (configs/scoring.yaml)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from riskdetect.scoring.result import Tier

DEFAULT_SCORING_PATH = Path("configs/scoring.yaml")


class ScoringConfigError(ValueError):
    """The scoring file is missing or invalid."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ConfidenceConfig(_Model):
    medium_from: int = Field(ge=1)
    high_from: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> "ConfidenceConfig":
        if self.high_from <= self.medium_from:
            raise ValueError("high_from must be above medium_from")
        return self


class TierConfig(_Model):
    watch_from: float = Field(gt=0, lt=1)
    review_from: float = Field(gt=0, lt=1)
    high_from: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> "TierConfig":
        if not self.watch_from < self.review_from < self.high_from:
            raise ValueError("tier thresholds must increase: watch < review < high")
        return self


class ScoringConfig(_Model):
    version: int = Field(ge=1)
    max_weight_score: float = Field(gt=0, le=1)
    confidence: ConfidenceConfig
    tiers: TierConfig
    actions: dict[Tier, tuple[str, ...]]
    allowlist_cap: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _every_tier_has_actions(self) -> "ScoringConfig":
        missing = set(Tier) - set(self.actions)
        if missing:
            raise ValueError(f"actions missing for tiers {sorted(missing)}")
        return self


def load_scoring_config(path: Path = DEFAULT_SCORING_PATH) -> ScoringConfig:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScoringConfigError(f"Scoring file not found: {path}") from exc
    try:
        return ScoringConfig.model_validate(data)
    except ValidationError as exc:
        raise ScoringConfigError(f"Invalid scoring file {path}:\n{exc}") from exc
