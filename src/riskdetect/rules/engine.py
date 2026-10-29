"""Run the rules against one user's features."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from riskdetect.rules.rule import Rule, RuleSet


@dataclass(frozen=True)
class RuleHit:
    rule: Rule
    # The values of the features the rule looked at, for explanations and audits.
    evidence: dict[str, Any]

    @property
    def active(self) -> bool:
        return self.rule.mode == "active"

    # The same shape as a model signal, so rule hits and signals combine identically.
    @property
    def code(self) -> str:
        return self.rule.id

    @property
    def category(self) -> str:
        return str(self.rule.category)

    @property
    def strength(self) -> float:
        return self.rule.strength

    @property
    def strong(self) -> bool:
        return self.rule.score_floor is not None

    @property
    def critical(self) -> bool:
        return self.rule.severity == "critical"


def evaluate(
    rules: RuleSet, values: Mapping[str, Any], packs: Collection[str] | None = None
) -> list[RuleHit]:
    """Every rule (active or shadow) whose condition holds for these feature values.

    With ``packs``, only rules from those packs apply (rules without a pack always do).
    """
    hits = []
    for rule in rules.rules:
        if packs is not None and rule.pack is not None and rule.pack not in packs:
            continue
        if rule.when.evaluate(values):
            evidence = {name: values.get(name) for name in sorted(rule.when.features())}
            hits.append(RuleHit(rule, evidence))
    return hits
