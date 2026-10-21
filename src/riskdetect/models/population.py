"""Population anomaly: is this user unusual compared with others on the same platform?

One Isolation Forest per platform, fitted on that platform's training snapshots,
using relative features only (percentiles and ratios), so "unusual" means
"unusual here". Missing values are filled with the platform's typical (median)
value, so missing data can never make someone look unusual.

Unusual is not the same as bad: very active, perfectly innocent users are unusual
too. So this signal is *weak*: on its own it can raise a user only to WATCH. It
adds weight when rules or other signals also point the same way.
"""

from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from statistics import median
from typing import Any

from riskdetect.models.isolation_forest import IsolationForest
from riskdetect.scoring.evidence import Signal

FEATURES: tuple[str, ...] = (
    "posts_1h_pct",
    "posts_24h_pct",
    "events_24h_pct",
    "distinct_spaces_7d_pct",
    "reports_received_7d_pct",
    "duplicate_ratio_24h",
    "duplicate_ratio_7d",
    "link_ratio_7d",
    "shortener_ratio_7d",
    "top_domain_share_7d",
    "timing_regularity",
    "active_hours_7d",
    "replies_per_post_7d",
)
CODE = "M001_population_anomaly"
UNUSUAL_FROM_PCT = 99.0  # flag only the most unusual 1% of training snapshots
MAX_STRENGTH = 0.35


class _PlatformModel:
    def __init__(
        self,
        forest: IsolationForest,
        fill: dict[str, float],
        score_reference: list[float],
        feature_reference: dict[str, list[float]],
    ) -> None:
        self.forest = forest
        self.fill = fill
        self.score_reference = score_reference
        self.feature_reference = feature_reference

    def vector(self, row: Mapping[str, Any]) -> list[float]:
        return [float(row[f]) if row.get(f) is not None else self.fill[f] for f in FEATURES]

    def percentile(self, row: Mapping[str, Any]) -> float:
        """Share of training snapshots that were less unusual than this one (0-100)."""
        score = self.forest.score(self.vector(row))
        return 100.0 * bisect_right(self.score_reference, score) / len(self.score_reference)

    def most_extreme(self, row: Mapping[str, Any], top: int = 3) -> list[tuple[str, float]]:
        """The features where this row sits furthest from the platform's typical value."""
        ranked = []
        for name in FEATURES:
            value = row.get(name)
            reference = self.feature_reference[name]
            if value is None or not reference:
                continue
            pct = 100.0 * bisect_right(reference, float(value)) / len(reference)
            ranked.append((abs(pct - 50.0), name, pct))
        ranked.sort(reverse=True)
        return [(name, pct) for _, name, pct in ranked[:top]]


class PopulationAnomaly:
    name = "population_anomaly"

    def __init__(self, platforms: dict[str, _PlatformModel] | None = None) -> None:
        self.platforms = platforms or {}

    @classmethod
    def fit(
        cls, rows_by_platform: Mapping[str, Sequence[Mapping[str, Any]]], seed: int = 0
    ) -> "PopulationAnomaly":
        """Fit one forest per platform on training snapshots (with percentile columns)."""
        models = {}
        for platform, rows in rows_by_platform.items():
            if len(rows) < 20:
                continue  # too few snapshots to learn what is normal
            values = {f: [float(r[f]) for r in rows if r.get(f) is not None] for f in FEATURES}
            fill = {f: median(v) if v else 0.0 for f, v in values.items()}
            model = _PlatformModel(IsolationForest(seed=seed), fill, [], {})
            vectors = [model.vector(r) for r in rows]
            model.forest.fit(vectors)
            model.score_reference = sorted(model.forest.score(v) for v in vectors)
            model.feature_reference = {f: sorted(v) for f, v in values.items()}
            models[platform] = model
        return cls(models)

    def signals(self, row: Mapping[str, Any]) -> list[Signal]:
        model = self.platforms.get(row["platform"])
        if model is None:
            return []
        pct = model.percentile(row)
        if pct < UNUSUAL_FROM_PCT:
            return []
        strength = MAX_STRENGTH * (pct - UNUSUAL_FROM_PCT) / (100.0 - UNUSUAL_FROM_PCT)
        extremes = model.most_extreme(row)
        detail = ", ".join(f"{name.replace('_', ' ')} (percentile {p:.0f})" for name, p in extremes)
        return [
            Signal(
                code=CODE,
                source=f"model:{self.name}",
                category="anomaly",
                strength=round(max(strength, 0.05), 4),
                strong=False,
                reason=f"Unusual compared with others on this platform (top {100 - pct:.1f}%): "
                f"{detail}",
                evidence={"anomaly_percentile": round(pct, 2), **dict(extremes)},
            )
        ]

    # -- saving ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": list(FEATURES),
            "platforms": {
                p: {
                    "forest": m.forest.to_dict(),
                    "fill": m.fill,
                    "score_reference": m.score_reference,
                    "feature_reference": m.feature_reference,
                }
                for p, m in self.platforms.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PopulationAnomaly":
        if list(data["features"]) != list(FEATURES):
            raise ValueError("saved model uses a different feature list; refit it")
        return cls(
            {
                p: _PlatformModel(
                    IsolationForest.from_dict(m["forest"]),
                    m["fill"],
                    m["score_reference"],
                    m["feature_reference"],
                )
                for p, m in data["platforms"].items()
            }
        )


def training_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Group snapshot rows by platform, ready for ``PopulationAnomaly.fit``."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["platform"], []).append(row)
    return grouped
