"""Rules and the rules file.

Rules are data (configs/rules.yaml), checked when loaded:
- every feature a rule mentions must exist (no typos silently never firing);
- a rule may not look at account age alone (being new is never a reason by itself);
- a rule must either set a score floor or carry a weight.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from riskdetect.features import PCT_SUFFIX, all_features
from riskdetect.rules.conditions import Condition
from riskdetect.schema import LabelCategory

# Features that describe an account's lifecycle, not its behavior.
LIFECYCLE_FEATURES = frozenset(
    f.name for f in all_features() if f.family in ("lifecycle", "evidence")
)


def known_feature_names() -> set[str]:
    names = {f.name for f in all_features()}
    names |= {f.name + PCT_SUFFIX for f in all_features() if f.percentile}
    return names


class RulesError(ValueError):
    """The rules file is missing or invalid."""


class Rule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^R\d{3}_[a-z0-9_]+$")
    description: str = Field(min_length=1)
    category: LabelCategory
    when: Condition
    reason: str = Field(min_length=1)
    score_floor: float | None = Field(default=None, ge=0.0, le=1.0)
    weight: float | None = Field(default=None, gt=0.0, le=1.0)
    severity: Literal["normal", "critical"] = "normal"
    mode: Literal["active", "shadow"] = "active"

    @model_validator(mode="after")
    def _check(self) -> "Rule":
        if self.category is LabelCategory.CLEAN:
            raise ValueError("a rule cannot point to the 'clean' category")
        if self.score_floor is None and self.weight is None:
            raise ValueError("a rule needs a score_floor or a weight")
        used = self.when.features()
        unknown = used - known_feature_names()
        if unknown:
            raise ValueError(f"unknown features {sorted(unknown)}")
        if used <= LIFECYCLE_FEATURES:
            raise ValueError("a rule must look at behavior, not only account age or history size")
        return self

    @property
    def strength(self) -> float:
        """How strongly a firing rule pushes the score (used to rank reasons)."""
        return max(self.score_floor or 0.0, self.weight or 0.0)


class RuleSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    rules: list[Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "RuleSet":
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return self


DEFAULT_RULES_PATH = Path("configs/rules.yaml")


def load_rules(path: Path = DEFAULT_RULES_PATH) -> RuleSet:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RulesError(f"Rules file not found: {path}") from exc
    try:
        return RuleSet.model_validate(data)
    except ValidationError as exc:
        problems = "\n".join(
            f"  {'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        )
        raise RulesError(f"Invalid rules file {path}:\n{problems}") from exc
