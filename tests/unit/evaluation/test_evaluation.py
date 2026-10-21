from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from riskdetect.evaluation import (
    NEW_ACCOUNTS,
    EvaluationConfig,
    Scored,
    SegmentRate,
    age_only,
    average_precision,
    check_gates,
    compute_metrics,
    last_days_cutoff,
    load_evaluation_config,
    platform_holdout,
    refit_percentiles,
    time_split,
    volume_only,
)
from riskdetect.labels import LabeledRow, Outcome

PROJECT_ROOT = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 8, 10, tzinfo=UTC)


class TestMetrics:
    def test_counts_and_rates(self) -> None:
        items = [
            Scored(0.9, True, 1),
            Scored(0.8, True, 0),
            Scored(0.7, False, 1),
            Scored(0.1, False, 0),
            Scored(0.0, False, 0),
        ]
        m = compute_metrics(items, ks=(1, 2))
        assert (m.true_positives, m.false_positives, m.positives, m.negatives) == (1, 1, 2, 3)
        assert m.precision == 0.5
        assert m.recall == 0.5
        assert m.false_positive_rate == pytest.approx(1 / 3)
        assert m.precision_at_k == {1: 1.0, 2: 0.5}

    def test_average_precision(self) -> None:
        perfect = [Scored(0.9, True, 1), Scored(0.8, True, 1), Scored(0.1, False, 0)]
        assert average_precision(perfect) == 1.0
        worst = [Scored(0.9, True, 0), Scored(0.1, False, 1)]
        assert average_precision(worst) == 0.5
        ties = [Scored(0.5, True, 1), Scored(0.5, True, 0)]  # a tie is one step, not two
        assert average_precision(ties) == 0.5
        assert average_precision([Scored(0.5, True, 0)]) is None

    def test_empty(self) -> None:
        m = compute_metrics([])
        assert (m.precision, m.recall, m.false_positive_rate, m.average_precision) == (
            None,
            None,
            None,
            None,
        )


class TestSplits:
    def rows(self) -> list[dict[str, Any]]:
        return [
            {"platform": p, "actor_id": "u", "as_of": T0 + timedelta(days=d), "posts_24h": float(d)}
            for p in ("a", "b")
            for d in range(10)
        ]

    def test_time_split_never_mixes_periods(self) -> None:
        cutoff = last_days_cutoff(self.rows(), days=3)
        assert cutoff == T0 + timedelta(days=7)
        train, test = time_split(self.rows(), cutoff)
        assert max(r["as_of"] for r in train) < cutoff <= min(r["as_of"] for r in test)
        assert len(test) == 6

    def test_platform_holdout(self) -> None:
        others, held = platform_holdout(self.rows(), "b")
        assert {r["platform"] for r in others} == {"a"}
        assert {r["platform"] for r in held} == {"b"}

    def test_percentiles_come_from_training_rows_only(self) -> None:
        train, test = time_split(self.rows(), T0 + timedelta(days=5))
        stale = [{**r, "posts_24h_pct": -1.0} for r in test if r["platform"] == "a"]
        refit = refit_percentiles("a", train, stale)
        # Training values are 0-4, so every test value (5-9) is above all of them.
        assert all(r["posts_24h_pct"] == 100.0 for r in refit)


def test_baselines() -> None:
    assert age_only({"account_age_days": 0.0}) > age_only({"account_age_days": 30.0})
    assert age_only({}) == 1.0
    assert volume_only({"posts_24h_pct": 50.0}) == 0.5
    assert volume_only({}) == 0.0


class TestGates:
    config = load_evaluation_config(PROJECT_ROOT / "configs" / "evaluation.yaml")

    def test_project_config_is_valid(self) -> None:
        assert isinstance(self.config, EvaluationConfig)
        assert "age_only" in self.config.gates.must_beat_baselines

    def test_unfair_detector_fails(self) -> None:
        good = compute_metrics([Scored(0.9, True, 1)] * 9 + [Scored(0.1, False, 0)] * 990)
        segments = [SegmentRate(NEW_ACCOUNTS, negatives=100, false_positives=5)]  # 5% of newcomers
        results = {g.name: g.passed for g in check_gates(good, segments, {}, self.config.gates)}
        assert results["precision"]
        assert not results["new-account false positive rate"]

    def test_must_beat_baselines(self) -> None:
        weak = compute_metrics([Scored(0.5, True, 1), Scored(0.5, True, 0)])
        strong_baseline = compute_metrics([Scored(0.9, True, 1), Scored(0.1, False, 0)])
        results = check_gates(weak, [], {"age_only": strong_baseline}, self.config.gates)
        beat = next(g for g in results if g.name == "beats age_only (average precision)")
        assert not beat.passed


def test_labeled_row_y() -> None:
    row = {"platform": "p", "actor_id": "u", "as_of": T0}
    assert LabeledRow(row, Outcome.POSITIVE, 1.0, None).y == 1
    assert LabeledRow(row, Outcome.UNLABELED, 0.3, None).y == 0
