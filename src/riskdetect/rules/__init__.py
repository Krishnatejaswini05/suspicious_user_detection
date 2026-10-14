"""Readable, configurable detection rules, with built-in fairness checks."""

from riskdetect.rules.conditions import Comparison, Condition, Group
from riskdetect.rules.engine import RuleHit, evaluate
from riskdetect.rules.rule import (
    DEFAULT_RULES_PATH,
    LIFECYCLE_FEATURES,
    Rule,
    RulesError,
    RuleSet,
    known_feature_names,
    load_rules,
)

__all__ = [
    "DEFAULT_RULES_PATH",
    "LIFECYCLE_FEATURES",
    "Comparison",
    "Condition",
    "Group",
    "Rule",
    "RuleHit",
    "RuleSet",
    "RulesError",
    "evaluate",
    "known_feature_names",
    "load_rules",
]
