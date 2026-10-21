import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from riskdetect.models import (
    IsolationForest,
    PopulationAnomaly,
    SelfBaselineAnomaly,
    change_score,
    load_models,
    save_population_model,
)
from riskdetect.models.__main__ import main
from riskdetect.models.isolation_forest import average_path
from riskdetect.models.population import FEATURES
from riskdetect.storage import ParquetFeatureStore

T0 = datetime(2026, 8, 20, tzinfo=UTC)


class TestIsolationForest:
    def crowd(self, n: int = 300, seed: int = 1) -> list[list[float]]:
        rng = random.Random(seed)
        return [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(n)]

    def test_outliers_score_higher_than_the_crowd(self) -> None:
        forest = IsolationForest(n_trees=50, seed=3).fit(self.crowd())
        assert forest.score([8.0, 8.0]) > 0.65
        assert forest.score([0.0, 0.0]) < 0.5

    def test_deterministic_and_round_trips(self) -> None:
        a = IsolationForest(seed=7).fit(self.crowd())
        b = IsolationForest(seed=7).fit(self.crowd())
        assert a.score([3.0, -2.0]) == b.score([3.0, -2.0])
        restored = IsolationForest.from_dict(json.loads(json.dumps(a.to_dict())))
        assert restored.score([3.0, -2.0]) == a.score([3.0, -2.0])

    def test_identical_rows_and_edge_cases(self) -> None:
        forest = IsolationForest(seed=0).fit([[1.0, 1.0]] * 10)
        assert 0 < forest.score([1.0, 1.0]) <= 1
        assert average_path(1) == 0.0 and average_path(2) == 1.0
        with pytest.raises(ValueError):
            IsolationForest().fit([])
        with pytest.raises(ValueError):
            IsolationForest().score([1.0])
        with pytest.raises(ValueError):
            IsolationForest(n_trees=0)


def snapshot(platform: str = "p", **values: float | None) -> dict[str, Any]:
    row: dict[str, Any] = {"platform": platform, "actor_id": "u", "as_of": T0}
    row.update({f: 50.0 if f.endswith("_pct") else 0.1 for f in FEATURES})
    row.update(values)
    return row


class TestPopulationAnomaly:
    def model(self) -> PopulationAnomaly:
        rng = random.Random(0)
        rows = [
            snapshot(
                posts_1h_pct=rng.uniform(0, 90),
                duplicate_ratio_7d=rng.uniform(0, 0.1),
                timing_regularity=rng.uniform(0.1, 0.4),
            )
            for _ in range(400)
        ]
        return PopulationAnomaly.fit({"p": rows, "tiny": rows[:5]})

    def test_only_the_most_unusual_get_a_weak_signal(self) -> None:
        model = self.model()
        assert "tiny" not in model.platforms  # too few snapshots to learn "normal"
        typical = snapshot(posts_1h_pct=45, duplicate_ratio_7d=0.05, timing_regularity=0.25)
        assert model.signals(typical) == []
        [signal] = model.signals(
            snapshot(posts_1h_pct=100, duplicate_ratio_7d=1.0, timing_regularity=0.99)
        )
        assert not signal.strong
        assert 0 < signal.strength <= 0.35
        assert "Unusual compared with others" in signal.reason

    def test_missing_values_never_look_unusual(self) -> None:
        model = self.model()
        assert model.signals(snapshot(**dict.fromkeys(FEATURES))) == []

    def test_unknown_platform_gives_nothing(self) -> None:
        assert self.model().signals(snapshot(platform="elsewhere")) == []

    def test_save_and_load(self, tmp_path: Path) -> None:
        model = self.model()
        save_population_model(model, tmp_path)
        loaded = load_models(tmp_path)
        assert [type(m).__name__ for m in loaded] == ["SelfBaselineAnomaly", "PopulationAnomaly"]
        odd = snapshot(posts_1h_pct=100, duplicate_ratio_7d=1.0, timing_regularity=0.99)
        assert loaded[1].signals(odd) == model.signals(odd)
        data = model.to_dict()
        data["features"] = ["something_else"]
        with pytest.raises(ValueError, match="refit"):
            PopulationAnomaly.from_dict(data)

    def test_without_a_fitted_model_only_self_baseline_loads(self, tmp_path: Path) -> None:
        assert [type(m).__name__ for m in load_models(tmp_path)] == ["SelfBaselineAnomaly"]


def established(**values: float | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "platform": "p",
        "actor_id": "u",
        "as_of": T0,
        "history_days": 60.0,
        "posts_24h": 20.0,
        "link_ratio_24h": 0.05,
        "link_ratio_before": 0.05,
        "duplicate_ratio_24h": 0.0,
        "duplicate_ratio_before": 0.0,
        "rate_vs_baseline": 1.0,
        "new_hours_share_24h": 0.0,
    }
    row.update(values)
    return row


class TestSelfBaseline:
    def test_takeover_is_a_strong_signal(self) -> None:
        takeover = established(link_ratio_24h=1.0, duplicate_ratio_24h=0.9, rate_vs_baseline=8.0)
        [signal] = SelfBaselineAnomaly().signals(takeover)
        assert signal.strong
        assert signal.category == "hijacked"
        assert "100% in the last day vs 5% usually" in signal.reason

    def test_new_accounts_are_never_judged(self) -> None:
        assert change_score(established(history_days=3.0, link_ratio_24h=1.0)) is None
        assert SelfBaselineAnomaly().signals(established(history_days=3.0)) == []

    def test_busy_day_alone_is_not_a_change(self) -> None:
        assert change_score(established(rate_vs_baseline=6.0)) == 0.0

    def test_a_couple_of_linked_posts_are_not_evidence(self) -> None:
        # 2 of 5 posts with links: a 35-point jump, but only ~2 extra posts behind it.
        few = established(posts_24h=5.0, link_ratio_24h=0.4, rate_vs_baseline=8.0)
        assert change_score(few) == 0.0

    def test_new_hours_only_support_a_change(self) -> None:
        drift = established(link_ratio_24h=0.6, new_hours_share_24h=1.0)
        assert change_score(drift) == pytest.approx(0.55 * 0.5)
        assert not SelfBaselineAnomaly().signals(drift)[0].strong


def test_command_line_fits_and_saves(tmp_path: Path) -> None:
    rng = random.Random(0)
    rows = [
        snapshot(platform="synthetic_forum", posts_1h_pct=rng.uniform(0, 90)) for _ in range(50)
    ]
    ParquetFeatureStore(tmp_path / "features").write("synthetic_forum", rows)
    configs = Path(__file__).resolve().parents[3] / "configs" / "platforms"
    assert main(["--data", str(tmp_path), "--config-dir", str(configs)]) == 0
    assert (tmp_path / "models" / "population_anomaly.json").exists()
