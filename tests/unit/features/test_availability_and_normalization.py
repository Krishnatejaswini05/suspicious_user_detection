from datetime import UTC, datetime
from pathlib import Path

import pytest

from riskdetect.adapters import load_platform_config
from riskdetect.features import (
    PercentileTable,
    feature_names,
    fields_from_config,
    fit_percentiles,
    get_feature,
    supported_features,
)
from riskdetect.storage import ParquetFeatureStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class TestAvailability:
    def test_fields_from_synthetic_configs(self) -> None:
        forum = fields_from_config(
            load_platform_config(PROJECT_ROOT / "configs/platforms/synthetic_forum.yaml")
        )
        assert {"text", "urls", "space_id", "content", "interactions", "reports"} <= forum
        assert "moderation" not in forum

    def test_features_need_their_fields(self) -> None:
        names = {f.name for f in supported_features({"content"})}
        assert "posts_24h" in names
        assert "duplicate_ratio_7d" not in names  # needs text
        assert "link_ratio_7d" not in names  # needs urls
        assert "account_age_days" in names  # needs nothing extra

    def test_none_means_everything(self) -> None:
        assert [f.name for f in supported_features(None)] == feature_names()

    def test_registry(self) -> None:
        assert get_feature("posts_1h").percentile
        assert not get_feature("duplicate_ratio_7d").percentile
        with pytest.raises(KeyError):
            get_feature("nope")


class TestPercentiles:
    def rows(self) -> list[dict[str, object]]:
        return [
            {"platform": "p", "posts_24h": float(v), "duplicate_ratio_7d": 0.5}
            for v in (0, 0, 0, 1, 2, 5, 10, 50)
        ] + [{"platform": "other", "posts_24h": 999.0}]

    def test_percentile_is_share_at_or_below(self) -> None:
        table = fit_percentiles("p", self.rows())
        assert table.percentile("posts_24h", 0.0) == pytest.approx(37.5)
        assert table.percentile("posts_24h", 50.0) == 100.0
        assert table.percentile("posts_24h", 3.0) == pytest.approx(62.5)
        assert table.percentile("posts_24h", None) is None
        assert "duplicate_ratio_7d" not in table.reference  # ratios are not converted

    def test_other_platforms_are_ignored(self) -> None:
        table = fit_percentiles("p", self.rows())
        assert max(table.reference["posts_24h"]) == 50.0

    def test_add_columns_and_round_trip(self, tmp_path: Path) -> None:
        table = fit_percentiles("p", self.rows())
        [row] = table.add_columns([{"platform": "p", "posts_24h": 10.0}])
        assert row["posts_24h_pct"] == pytest.approx(87.5)
        path = tmp_path / "pct.json"
        table.save(path)
        assert PercentileTable.load(path) == table


def test_feature_store_round_trip(tmp_path: Path) -> None:
    store = ParquetFeatureStore(tmp_path / "features")
    rows = [
        {"platform": "p", "actor_id": "u1", "as_of": datetime(2026, 8, 1, tzinfo=UTC), "x": None}
    ]
    store.write("p", rows)
    store.write("p", rows)  # rewriting replaces, never accumulates
    assert store.read("p") == rows
    assert store.read("missing") == []
