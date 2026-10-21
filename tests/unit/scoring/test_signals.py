"""Model signals combine with rules the same way, with the same guardrails."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import EventFactory
from riskdetect.features import FeatureEngine
from riskdetect.rules import RuleSet
from riskdetect.scoring import Scorer, ScoringConfig, Signal, Tier

AS_OF = datetime(2026, 8, 20, tzinfo=UTC)
CONFIG = ScoringConfig.model_validate(
    {
        "version": 1,
        "max_weight_score": 0.55,
        "confidence": {"medium_from": 10, "high_from": 40},
        "tiers": {"watch_from": 0.3, "review_from": 0.6, "high_from": 0.85},
        "actions": {"LOW": [], "WATCH": [], "REVIEW": [], "HIGH": []},
        "allowlist_cap": 0.2,
    }
)
RULES = RuleSet.model_validate(
    {
        "version": 1,
        "rules": [
            {
                "id": "R001_burst",
                "description": "burst",
                "category": "spam",
                "score_floor": 0.75,
                "when": {"all": [{"feature": "posts_1h", "op": ">=", "value": 10}]},
                "reason": "burst",
            }
        ],
    }
)


class FixedModel:
    name = "fixed"

    def __init__(self, strength: float, strong: bool) -> None:
        self.signal = Signal("M900_fixed", "model:fixed", "anomaly", strength, strong, "odd")

    def signals(self, row: Mapping[str, Any]) -> list[Signal]:
        return [self.signal]


def row(**values: float) -> dict[str, Any]:
    return {"platform": "p", "actor_id": "u", "as_of": AS_OF, "events_seen": 100.0, **values}


def test_weak_signal_alone_reaches_at_most_watch() -> None:
    result = Scorer(RULES, CONFIG, models=[FixedModel(0.9, strong=False)]).score(row())
    assert result.score == 0.55
    assert result.tier is Tier.WATCH
    assert result.signals == ("M900_fixed",)
    assert result.reasons[0].text == "odd"


def test_strong_signal_can_escalate() -> None:
    result = Scorer(RULES, CONFIG, models=[FixedModel(0.7, strong=True)]).score(row())
    assert result.tier is Tier.REVIEW


def test_signals_add_to_rule_evidence() -> None:
    alone = Scorer(RULES, CONFIG).score(row(posts_1h=10))
    together = Scorer(RULES, CONFIG, models=[FixedModel(0.3, strong=False)]).score(row(posts_1h=10))
    assert together.score > alone.score
    assert [r.code for r in together.reasons] == ["R001_burst", "M900_fixed"]


def test_with_models_keeps_everything_else() -> None:
    base = Scorer(RULES, CONFIG, allowlist=[("p", "u")])
    swapped = base.with_models([FixedModel(0.9, strong=True)])
    assert swapped.score(row()).score == 0.2  # allowlist still applies


def test_self_baseline_features(make_event: EventFactory) -> None:
    engine = FeatureEngine("synthetic_forum")
    for day in range(20, 1, -1):  # a quiet month: one post a day at 10:00, no links
        engine.apply(
            make_event(
                occurred_at=AS_OF - timedelta(days=day) + timedelta(hours=10),
                content={"kind": "post", "text_hash": f"{day:064x}"},
            )
        )
    for minute in range(12):  # then a burst of links at 03:00
        engine.apply(
            make_event(
                occurred_at=AS_OF - timedelta(hours=21) + timedelta(minutes=minute),
                content={"kind": "post", "url_domains": ["scam.xyz"], "text_hash": "a" * 64},
            )
        )
    values = engine.compute("u1", AS_OF)
    assert values["history_days"] is not None and values["history_days"] > 18
    assert values["link_ratio_before"] == 0.0
    assert values["link_ratio_24h"] == 1.0
    assert values["new_hours_share_24h"] == 1.0
