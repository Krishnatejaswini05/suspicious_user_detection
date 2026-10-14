"""Run the rules against one user's features."""

from collections.abc import Mapping
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


def evaluate(rules: RuleSet, values: Mapping[str, Any]) -> list[RuleHit]:
    """Every rule (active or shadow) whose condition holds for these feature values."""
    hits = []
    for rule in rules.rules:
        if rule.when.evaluate(values):
            evidence = {name: values.get(name) for name in sorted(rule.when.features())}
            hits.append(RuleHit(rule, evidence))
    return hits
