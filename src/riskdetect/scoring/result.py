"""What a score looks like."""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from riskdetect.explain import Reason


class Tier(StrEnum):
    LOW = "LOW"
    WATCH = "WATCH"
    REVIEW = "REVIEW"
    HIGH = "HIGH"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RiskResult:
    platform: str
    actor_id: str
    as_of: datetime
    score: float  # 0-1
    tier: Tier
    confidence: Confidence
    categories: dict[str, float]  # e.g. {"spam": 0.75, "bot": 0.7}
    reasons: tuple[Reason, ...]
    rules_fired: tuple[str, ...]  # active rules that fired
    shadow_rules: tuple[str, ...]  # shadow rules that would have fired
    actions: tuple[str, ...]  # recommendations only; the platform decides
    rules_version: int
    scoring_version: int
    signals: tuple[str, ...] = ()  # model signals that contributed (e.g. anomaly detectors)

    def to_row(self) -> dict[str, Any]:
        """A flat row for the score store."""
        return {
            "platform": self.platform,
            "actor_id": self.actor_id,
            "as_of": self.as_of,
            "score": self.score,
            "tier": str(self.tier),
            "confidence": str(self.confidence),
            "categories": json.dumps(self.categories, sort_keys=True),
            "reasons": [r.text for r in self.reasons],
            "reason_codes": [r.code for r in self.reasons],
            "rules_fired": list(self.rules_fired),
            "shadow_rules": list(self.shadow_rules),
            "actions": list(self.actions),
            "rules_version": self.rules_version,
            "scoring_version": self.scoring_version,
            "signals": list(self.signals),
        }
