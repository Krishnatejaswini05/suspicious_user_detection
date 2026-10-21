"""Turn one user's features into a score, confidence, tier, reasons and actions.

Steps:
1. Run the rules (rules/) and ask each model (e.g. anomaly detectors) for signals.
2. Combine: each piece of evidence removes a share of the remaining doubt,
   score = 1 - product(1 - strength). One strong rule at 0.75 gives 0.75; two
   independent strong signals give more. Weak evidence alone is capped below REVIEW.
3. Confidence from how much we have seen of the user.
4. Guardrails: allowlist cap; HIGH needs high confidence and at least two independent
   pieces of evidence (unless a critical rule fired), so a single worried voice, rule or
   model, sends a user to a person (REVIEW) first; nothing above WATCH without a reason.
5. Tier and recommended actions.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from riskdetect.explain import MAX_REASONS, Reason, top_reasons
from riskdetect.rules import RuleSet, evaluate
from riskdetect.scoring.config import ScoringConfig
from riskdetect.scoring.evidence import Evidence, Signal, SignalSource
from riskdetect.scoring.result import Confidence, RiskResult, Tier


def combine(items: Iterable[Evidence], max_weight_score: float) -> tuple[float, dict[str, float]]:
    """Overall score and a score per category, from active rule hits and model signals."""
    active = [item for item in items if item.active]

    def merged(group: list[Evidence]) -> float:
        doubt = 1.0
        for item in group:
            doubt *= 1.0 - item.strength
        score = 1.0 - doubt
        if not any(item.strong for item in group):
            score = min(score, max_weight_score)  # weak evidence alone stays below REVIEW
        return round(score, 4)

    by_category: dict[str, list[Evidence]] = {}
    for item in active:
        by_category.setdefault(item.category, []).append(item)
    categories = {category: merged(group) for category, group in sorted(by_category.items())}
    return (merged(active) if active else 0.0), categories


def _signal_reason(signal: Signal) -> Reason:
    return Reason(
        code=signal.code,
        source=signal.source,
        category=signal.category,
        text=signal.reason,
        strength=signal.strength,
        evidence=dict(signal.evidence),
    )


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
        models: Iterable[SignalSource] = (),
    ) -> None:
        """``allowlist`` holds (platform, actor_id) pairs, e.g. staff or official bots.
        ``models`` are extra evidence sources, such as the anomaly detectors."""
        self.rules = rules
        self.config = config
        self.allowlist = frozenset(allowlist)
        self.models = tuple(models)

    def with_models(self, models: Iterable[SignalSource]) -> "Scorer":
        """The same scorer with a different set of models (e.g. fitted on a training period)."""
        return Scorer(self.rules, self.config, self.allowlist, models)

    def score(self, row: Mapping[str, Any]) -> RiskResult:
        """Score one feature row (platform, actor_id, as_of plus feature values)."""
        platform, actor_id, as_of = row["platform"], row["actor_id"], row["as_of"]
        hits = evaluate(self.rules, row)
        signals = [signal for model in self.models for signal in model.signals(row)]
        score, categories = combine([*hits, *signals], self.config.max_weight_score)

        if (platform, actor_id) in self.allowlist:
            score = min(score, self.config.allowlist_cap)
            categories = {c: min(v, self.config.allowlist_cap) for c, v in categories.items()}

        candidates = top_reasons(hits) + [_signal_reason(s) for s in signals]
        candidates.sort(key=lambda r: (-r.strength, r.code))
        reasons = tuple(candidates[:MAX_REASONS])
        confidence = confidence_from(row.get("events_seen"), self.config)
        critical = any(h.active and h.critical for h in hits)
        tier = tier_from(score, confidence, critical, self.config)
        evidence_count = sum(1 for h in hits if h.active) + len(signals)
        if tier is Tier.HIGH and evidence_count < 2 and not critical:
            tier = Tier.REVIEW  # one voice alone: a person checks before strong action
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
            signals=tuple(s.code for s in signals),
        )

    def score_all(self, rows: Iterable[Mapping[str, Any]]) -> list[RiskResult]:
        return [self.score(row) for row in rows]


def _as_datetime(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"as_of must be a datetime, got {type(value).__name__}")
    return value
