"""Express raw counts as percentiles within their own platform.

50 posts a day is ordinary in chat and extreme on a marketplace. "Above 99.9% of
users on this platform" means the same everywhere, which is what lets one model
work across platforms.

Percentiles must be fitted on a reference period. For training and evaluation
(later milestones) that is the training period only, so the test period cannot
leak into the reference.
"""

import json
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from riskdetect.features.batch import FeatureRow
from riskdetect.features.definition import Feature
from riskdetect.features.registry import all_features

PCT_SUFFIX = "_pct"


@dataclass
class PercentileTable:
    platform: str
    reference: dict[str, list[float]] = field(default_factory=dict)  # sorted values per feature

    def percentile(self, feature: str, value: float | None) -> float | None:
        """Share of reference values <= value, in 0-100. None stays None."""
        values = self.reference.get(feature)
        if value is None or not values:
            return None
        return 100.0 * bisect_right(values, value) / len(values)

    def add_columns(self, rows: Iterable[FeatureRow]) -> list[FeatureRow]:
        """Copies of ``rows`` with a ``<feature>_pct`` column for each fitted feature."""
        out = []
        for row in rows:
            enriched = dict(row)
            for name in self.reference:
                enriched[name + PCT_SUFFIX] = self.percentile(name, row.get(name))
            out.append(enriched)
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"platform": self.platform, "reference": self.reference}), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "PercentileTable":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data["platform"], data["reference"])


def fit_percentiles(
    platform: str, rows: Iterable[FeatureRow], features: Iterable[Feature] | None = None
) -> PercentileTable:
    """Learn each count feature's distribution on one platform from reference rows."""
    selected = [f for f in (features or all_features()) if f.percentile]
    values: dict[str, list[float]] = {f.name: [] for f in selected}
    for row in rows:
        if row.get("platform") != platform:
            continue
        for name in values:
            value = row.get(name)
            if value is not None:
                values[name].append(float(value))
    return PercentileTable(platform, {name: sorted(v) for name, v in values.items() if v})
