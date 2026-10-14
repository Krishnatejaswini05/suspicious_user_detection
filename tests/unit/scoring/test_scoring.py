from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from riskdetect.explain import render, top_reasons
from riskdetect.rules import RuleSet, evaluate
from riskdetect.scoring import (
    Confidence,
    Scorer,
    ScoringConfig,
    ScoringConfigError,
    Tier,
    combine,
    load_scoring_config,
)
from riskdetect.storage import ParquetScoreStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AS_OF = datetime(2026, 8, 20, tzinfo=UTC)

CONFIG = ScoringConfig.model_validate(
    {
        "version": 1,
        "max_weight_score": 0.55,
        "confidence": {"medium_from": 10, "high_from": 40},
        "tiers": {"watch_from": 0.3, "review_from": 0.6, "high_from": 0.85},
        "actions": {"LOW": [], "WATCH": ["monitor"], "REVIEW": ["review"], "HIGH": ["review"]},
        "allowlist_cap": 0.2,
    }
)


def rule(rid: str, feature: str, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": rid,
        "description": rid,
        "category": "spam",
        "when": {"all": [{"feature": feature, "op": ">=", "value": 1}]},
        "reason": f"{feature} is {{{feature}:.0f}}",
    }
    data.update(extra)
    return data


RULES = RuleSet.model_validate(
    {
        "version": 3,
        "rules": [
            rule("R001_strong", "posts_1h", score_floor=0.75),
            rule("R002_strong_bot", "timing_regularity", score_floor=0.6, category="bot"),
            rule("R003_weak", "link_ratio_7d", weight=0.3),
            rule("R004_weak", "shortener_ratio_7d", weight=0.3),
            rule("R005_critical", "reports_received_7d", score_floor=0.9, severity="critical"),
            rule("R006_shadow", "posts_7d", score_floor=0.9, mode="shadow"),
        ],
    }
)


def row(events_seen: float = 100, **features: float) -> dict[str, Any]:
    return {
        "platform": "synthetic_forum",
        "actor_id": "u1",
        "as_of": AS_OF,
        "events_seen": events_seen,
        **features,
    }


@pytest.fixture
def scorer() -> Scorer:
    return Scorer(RULES, CONFIG)


class TestCombine:
    def test_evidence_adds_up(self) -> None:
        one, _ = combine(evaluate(RULES, row(posts_1h=1)), 0.55)
        two, categories = combine(evaluate(RULES, row(posts_1h=1, timing_regularity=1)), 0.55)
        assert one == 0.75
        assert two == pytest.approx(1 - 0.25 * 0.4)
        assert categories == {"bot": 0.6, "spam": 0.75}

    def test_weak_signals_alone_stay_below_review(self) -> None:
        score, _ = combine(evaluate(RULES, row(link_ratio_7d=1, shortener_ratio_7d=1)), 0.55)
        assert score == pytest.approx(min(1 - 0.7 * 0.7, 0.55))

    def test_shadow_rules_do_not_count(self) -> None:
        assert combine(evaluate(RULES, row(posts_7d=1)), 0.55) == (0.0, {})


class TestScorer:
    def test_clean_user(self, scorer: Scorer) -> None:
        result = scorer.score(row())
        assert (result.score, result.tier, result.reasons) == (0.0, Tier.LOW, ())

    def test_strong_evidence_reaches_high(self, scorer: Scorer) -> None:
        result = scorer.score(row(posts_1h=1, timing_regularity=1, link_ratio_7d=1))
        assert result.tier is Tier.HIGH
        assert result.actions == ("review",)
        assert result.rules_fired == ("R001_strong", "R002_strong_bot", "R003_weak")
        assert result.reasons[0].code == "R001_strong"  # strongest first
        assert result.rules_version == 3

    def test_thin_evidence_stops_at_review(self, scorer: Scorer) -> None:
        result = scorer.score(row(events_seen=5, posts_1h=1, timing_regularity=1))
        assert result.confidence is Confidence.LOW
        assert result.score >= CONFIG.tiers.high_from
        assert result.tier is Tier.REVIEW  # a person looks; never HIGH on little data

    def test_critical_rule_may_reach_high_on_thin_evidence(self, scorer: Scorer) -> None:
        result = scorer.score(row(events_seen=5, reports_received_7d=1))
        assert result.tier is Tier.HIGH

    def test_allowlisted_accounts_are_capped(self) -> None:
        scorer = Scorer(RULES, CONFIG, allowlist=[("synthetic_forum", "u1")])
        result = scorer.score(row(posts_1h=1, timing_regularity=1))
        assert result.score == 0.2
        assert result.tier is Tier.LOW

    def test_shadow_rules_are_recorded_but_harmless(self, scorer: Scorer) -> None:
        result = scorer.score(row(posts_7d=1))
        assert result.shadow_rules == ("R006_shadow",)
        assert (result.score, result.reasons) == (0.0, ())

    def test_confidence_levels(self, scorer: Scorer) -> None:
        assert scorer.score(row(events_seen=3)).confidence is Confidence.LOW
        assert scorer.score(row(events_seen=10)).confidence is Confidence.MEDIUM
        assert scorer.score(row(events_seen=40)).confidence is Confidence.HIGH
        assert scorer.score({**row(), "events_seen": None}).confidence is Confidence.LOW


class TestReasons:
    def test_render_fills_values_and_tidies_whitespace(self) -> None:
        assert render("Posted {n:.0f}\n  times ({p:.0%})", {"n": 38.0, "p": 0.97}) == (
            "Posted 38 times (97%)"
        )

    def test_unknown_values_read_as_unknown(self) -> None:
        assert render("rate {x:.1f}", {"x": None}) == "rate unknown"
        assert render("rate {x:.1f}", {}) == "rate unknown"

    def test_top_reasons_excludes_shadow_and_limits(self) -> None:
        hits = evaluate(RULES, row(posts_1h=1, link_ratio_7d=1, posts_7d=1))
        reasons = top_reasons(hits, limit=1)
        assert [r.code for r in reasons] == ["R001_strong"]
        assert reasons[0].text == "posts_1h is 1"


class TestConfigFiles:
    def test_project_scoring_file_is_valid(self) -> None:
        config = load_scoring_config(PROJECT_ROOT / "configs" / "scoring.yaml")
        # Weak signals alone must never reach REVIEW.
        assert config.max_weight_score < config.tiers.review_from

    @pytest.mark.parametrize(
        "change",
        [
            {"tiers": {"watch_from": 0.6, "review_from": 0.3, "high_from": 0.85}},
            {"confidence": {"medium_from": 50, "high_from": 10}},
            {"actions": {"LOW": []}},
        ],
    )
    def test_invalid(self, change: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            ScoringConfig.model_validate({**CONFIG.model_dump(), **change})

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ScoringConfigError):
            load_scoring_config(tmp_path / "missing.yaml")


def test_score_store_round_trip(scorer: Scorer, tmp_path: Path) -> None:
    store = ParquetScoreStore(tmp_path / "scores")
    results = [scorer.score(row(posts_1h=1)), scorer.score({**row(), "actor_id": "u2"})]
    store.write("synthetic_forum", [r.to_row() for r in results])
    stored = store.read("synthetic_forum")
    assert [(r["actor_id"], r["tier"]) for r in stored] == [("u1", "REVIEW"), ("u2", "LOW")]
    assert stored[0]["reasons"] == ["posts_1h is 1"]
    assert store.read("nowhere") == []
