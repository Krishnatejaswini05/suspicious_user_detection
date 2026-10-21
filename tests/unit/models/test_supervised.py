import json
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from riskdetect.labels import ActorTruth
from riskdetect.models import (
    BoostingParams,
    GradientBoostedTrees,
    IsotonicCalibrator,
    SupervisedClassifier,
    classifier_features,
    train_classifier,
)
from riskdetect.models.classifier import MIN_POSTS_7D
from riskdetect.schema import Label

T0 = datetime(2026, 8, 1, tzinfo=UTC)


class TestBoostedTrees:
    def data(self, n: int = 600, seed: int = 0) -> tuple[list[list[float | None]], list[int]]:
        """Bad only when BOTH a and b are high: a combination no single split captures."""
        rng = random.Random(seed)
        rows: list[list[float | None]] = []
        labels = []
        for _ in range(n):
            a, b = rng.random(), rng.random()
            rows.append([a, b, rng.random()])
            labels.append(int(a > 0.6 and b > 0.6))
        return rows, labels

    def test_learns_combinations(self) -> None:
        rows, labels = self.data()
        model = GradientBoostedTrees(BoostingParams(n_trees=60, seed=1)).fit(rows, labels)
        assert model.predict_proba([0.9, 0.9, 0.5]) > 0.8
        assert model.predict_proba([0.9, 0.1, 0.5]) < 0.2
        assert model.predict_proba([0.1, 0.9, 0.5]) < 0.2

    def test_missing_values_take_a_learned_side(self) -> None:
        rows, labels = self.data()
        rows = [[None if i % 5 == 0 else r[0], r[1], r[2]] for i, r in enumerate(rows)]
        model = GradientBoostedTrees(BoostingParams(n_trees=30)).fit(rows, labels)
        assert 0 < model.predict_proba([None, 0.9, 0.5]) < 1

    def test_contributions_explain_the_score(self) -> None:
        rows, labels = self.data()
        model = GradientBoostedTrees(BoostingParams(n_trees=30)).fit(rows, labels)
        row: list[float | None] = [0.9, 0.9, 0.5]
        contributions = model.contributions(row)
        assert model.baseline() + sum(contributions) == pytest.approx(model.margin(row))
        assert contributions[2] < max(contributions[0], contributions[1])  # noise matters least

    def test_deterministic_and_round_trips(self) -> None:
        rows, labels = self.data()
        a = GradientBoostedTrees(BoostingParams(n_trees=20, seed=3)).fit(rows, labels)
        b = GradientBoostedTrees(BoostingParams(n_trees=20, seed=3)).fit(rows, labels)
        restored = GradientBoostedTrees.from_dict(json.loads(json.dumps(a.to_dict())))
        for row in ([0.9, 0.9, 0.1], [0.2, 0.7, None]):
            assert a.predict_proba(row) == b.predict_proba(row) == restored.predict_proba(row)

    def test_needs_both_classes(self) -> None:
        with pytest.raises(ValueError):
            GradientBoostedTrees().fit([[1.0]] * 5, [0] * 5)
        with pytest.raises(ValueError):
            GradientBoostedTrees().fit([], [])


class TestCalibration:
    def test_monotonic_and_honest(self) -> None:
        scores = [0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9]
        labels = [0, 0, 1, 0, 1, 1, 1, 1]
        calibrator = IsotonicCalibrator().fit(scores, labels)
        values = [calibrator(s / 10) for s in range(11)]
        assert values == sorted(values)  # a higher raw score never means less risk
        assert calibrator(0.0) == 0.0
        assert calibrator(1.0) == 1.0

    def test_unseen_middle_scores_stay_in_the_middle(self) -> None:
        # No calibration examples between 0.1 and 0.9: a step function would jump to 1.0.
        calibrator = IsotonicCalibrator().fit([0.0, 0.1, 0.9, 1.0], [0, 0, 1, 1])
        assert 0.2 < calibrator(0.5) < 0.8

    def test_round_trip(self) -> None:
        calibrator = IsotonicCalibrator().fit([0.1, 0.5, 0.9], [0, 1, 1])
        restored = IsotonicCalibrator.from_dict(json.loads(json.dumps(calibrator.to_dict())))
        assert restored(0.7) == calibrator(0.7)
        with pytest.raises(ValueError):
            IsotonicCalibrator()(0.5)


def test_classifier_never_sees_age_or_history() -> None:
    names = set(classifier_features())
    assert not names & {"account_age_days", "hours_to_first_post", "events_seen", "history_days"}
    assert "posts_1h_pct" in names and "posts_1h" not in names  # counts as percentiles


def training_world(
    days: int = 12,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], ActorTruth]]:
    """Two platforms; bad users repeat themselves and post links, good ones don't."""
    rng = random.Random(0)
    rows, truths = [], {}
    for platform in ("forum", "chat"):
        for n in range(40):
            actor = f"u{n}"
            bad = n < 6
            truths[(platform, actor)] = ActorTruth(
                platform,
                actor,
                Label(
                    actor_id=actor,
                    platform=platform,
                    category="spam" if bad else "clean",
                    abuse_start=T0 if bad else None,
                    decided_at=T0 + timedelta(days=days),
                    source="synthetic",
                ),
            )
            for day in range(days):
                rows.append(
                    {
                        "platform": platform,
                        "actor_id": actor,
                        "as_of": T0 + timedelta(days=day, hours=1),
                        "posts_7d": 20.0,
                        "duplicate_ratio_7d": rng.uniform(0.7, 1) if bad else rng.uniform(0, 0.1),
                        "link_ratio_7d": rng.uniform(0.8, 1) if bad else rng.uniform(0, 0.2),
                        "posts_1h_pct": rng.uniform(80, 100) if bad else rng.uniform(0, 90),
                    }
                )
    return rows, truths


class TestClassifier:
    def model(self) -> SupervisedClassifier:
        rows, truths = training_world()
        return train_classifier(rows, truths, params=BoostingParams(n_trees=30))

    def spammy(self, platform: str = "forum", **extra: Any) -> dict[str, Any]:
        return {
            "platform": platform,
            "actor_id": "x",
            "as_of": T0,
            "posts_7d": 20.0,
            "duplicate_ratio_7d": 0.95,
            "link_ratio_7d": 0.95,
            "posts_1h_pct": 99.0,
            **extra,
        }

    def test_flags_known_abusive_behavior_with_reasons(self) -> None:
        model = self.model()
        [signal] = model.signals(self.spammy())
        assert signal.strong
        assert "Behaves like known abusive accounts" in signal.reason
        assert "duplicate ratio 7d" in signal.reason or "link ratio 7d" in signal.reason
        calm = self.spammy(duplicate_ratio_7d=0.02, link_ratio_7d=0.05, posts_1h_pct=40.0)
        assert model.signals(calm) == []

    def test_advisory_only_on_platforms_it_never_learned(self) -> None:
        model = self.model()
        assert model.trained_platforms == {"forum", "chat"}
        [signal] = model.signals(self.spammy(platform="market"))
        assert not signal.strong
        assert "advisory" in signal.reason

    def test_silent_until_a_user_has_enough_posts(self) -> None:
        assert self.model().signals(self.spammy(posts_7d=float(MIN_POSTS_7D - 1))) == []

    def test_round_trip(self) -> None:
        model = self.model()
        restored = SupervisedClassifier.from_dict(json.loads(json.dumps(model.to_dict())))
        assert restored.probability(self.spammy()) == model.probability(self.spammy())
        assert restored.trained_platforms == model.trained_platforms
        data = model.to_dict()
        data["features"] = ["other"]
        with pytest.raises(ValueError, match="retrain"):
            SupervisedClassifier.from_dict(data)

    def test_needs_labels(self) -> None:
        rows, _ = training_world()
        with pytest.raises(ValueError):
            train_classifier(rows, {})
