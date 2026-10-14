"""Turn one user's features into a score, confidence, tier, reasons and actions.

Steps:
1. Run the rules (rules/).
2. Combine: each fired rule removes a share of the remaining doubt,
   score = 1 - product(1 - strength). One strong rule at 0.75 gives 0.75; two
   independent strong rules give more. Weak signals alone are capped below REVIEW.
   Later milestones blend in anomaly and model scores here.
3. Confidence from how much we have seen of the user.
4. Guardrails: allowlist cap; HIGH needs high confidence (unless a critical rule
   fired); nothing above WATCH without at least one reason.
5. Tier and recommended actions.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from riskdetect.explain import top_reasons
from riskdetect.rules import Rule, RuleHit, RuleSet, evaluate
from riskdetect.scoring.config import ScoringConfig
from riskdetect.scoring.result import Confidence, RiskResult, Tier


def combine(hits: Iterable[RuleHit], max_weight_score: float) -> tuple[float, dict[str, float]]:
    """Overall score and a score per abuse category, from the active rules that fired."""
    active = [hit.rule for hit in hits if hit.active]

    def merged(rules: list[Rule]) -> float:
        doubt = 1.0
        for rule in rules:
            doubt *= 1.0 - rule.strength
        score = 1.0 - doubt
        if not any(rule.score_floor is not None for rule in rules):
            score = min(score, max_weight_score)  # weak signals alone stay below REVIEW
        return round(score, 4)

    by_category: dict[str, list[Rule]] = {}
    for rule in active:
        by_category.setdefault(str(rule.category), []).append(rule)
    categories = {category: merged(rules) for category, rules in sorted(by_category.items())}
    return (merged(active) if active else 0.0), categories


def confidence_from(events_seen: float | None, config: ScoringConfig) -> Confidence:
    seen = events_seen or 0
    if seen >= config.confidence.high_from:
        return Confidence.HIGH
    if seen >= config.confidence.medium_from:
        return Confidence.MEDIUM
    return Confidence.LOW


def tier_from(score: float, confidence: Confidence, critical: bool, config: ScoringConfig) -> Tier:
    t = config.tiers
    if score >= t.high_from and (confidence is Confidence.HIGH or critical):
        return Tier.HIGH
    if score >= t.review_from:
        return Tier.REVIEW  # includes high scores on thin evidence: a person looks first
    if score >= t.watch_from:
        return Tier.WATCH
    return Tier.LOW


class Scorer:
    def __init__(
        self,
        rules: RuleSet,
        config: ScoringConfig,
        allowlist: Iterable[tuple[str, str]] = (),
    ) -> None:
        """``allowlist`` holds (platform, actor_id) pairs, e.g. staff or official bots."""
        self.rules = rules
        self.config = config
        self.allowlist = frozenset(allowlist)

    def score(self, row: Mapping[str, Any]) -> RiskResult:
        """Score one feature row (platform, actor_id, as_of plus feature values)."""
        platform, actor_id, as_of = row["platform"], row["actor_id"], row["as_of"]
        hits = evaluate(self.rules, row)
        score, categories = combine(hits, self.config.max_weight_score)

        if (platform, actor_id) in self.allowlist:
            score = min(score, self.config.allowlist_cap)
            categories = {c: min(v, self.config.allowlist_cap) for c, v in categories.items()}

        reasons = tuple(top_reasons(hits))
        confidence = confidence_from(row.get("events_seen"), self.config)
        critical = any(h.active and h.rule.severity == "critical" for h in hits)
        tier = tier_from(score, confidence, critical, self.config)
        if tier in (Tier.REVIEW, Tier.HIGH) and not reasons:
            tier = Tier.WATCH  # never escalate without something a person can check

        return RiskResult(
            platform=platform,
            actor_id=actor_id,
            as_of=_as_datetime(as_of),
            score=score,
            tier=tier,
            confidence=confidence,
            categories=categories,
            reasons=reasons,
            rules_fired=tuple(h.rule.id for h in hits if h.active),
            shadow_rules=tuple(h.rule.id for h in hits if not h.active),
            actions=self.config.actions[tier],
            rules_version=self.rules.version,
            scoring_version=self.config.version,
        )

    def score_all(self, rows: Iterable[Mapping[str, Any]]) -> list[RiskResult]:
        return [self.score(row) for row in rows]


def _as_datetime(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"as_of must be a datetime, got {type(value).__name__}")
    return value
