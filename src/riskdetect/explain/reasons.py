"""Readable reasons for a score.

Every reason has a stable ``code`` (for counting and auditing) and ``text`` for
people, filled in with the actual values that triggered it. Shadow rules never
produce reasons, because they never affect scores.
"""

import string
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from riskdetect.rules import RuleHit

MAX_REASONS = 5
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Reason:
    code: str
    source: str
    category: str
    text: str
    strength: float
    evidence: dict[str, Any]


class _ValueFormatter(string.Formatter):
    """Fills ``{feature:.1f}`` placeholders; missing values read as "unknown"."""

    def get_value(self, key: int | str, args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any:
        return kwargs.get(str(key))

    def format_field(self, value: Any, format_spec: str) -> str:
        if value is None:
            return UNKNOWN
        return str(super().format_field(value, format_spec))


_FORMATTER = _ValueFormatter()


def render(template: str, values: Mapping[str, Any]) -> str:
    """Fill a reason template and tidy the whitespace left by multi-line YAML."""
    return " ".join(_FORMATTER.vformat(template, (), values).split())


def reason_for(hit: RuleHit) -> Reason:
    rule = hit.rule
    return Reason(
        code=rule.id,
        source=f"rule:{rule.id}",
        category=str(rule.category),
        text=render(rule.reason, hit.evidence),
        strength=rule.strength,
        evidence=dict(hit.evidence),
    )


def top_reasons(hits: Iterable[RuleHit], limit: int = MAX_REASONS) -> list[Reason]:
    """The strongest reasons from active rules, strongest first."""
    reasons = [reason_for(hit) for hit in hits if hit.active]
    reasons.sort(key=lambda r: (-r.strength, r.code))
    return reasons[:limit]
