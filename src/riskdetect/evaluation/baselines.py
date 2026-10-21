"""Lazy shortcuts the detector must beat.

If a detector cannot beat "flag the newest accounts" or "flag the busiest users",
it is not adding value, and the age shortcut is exactly the unfairness we promised
to avoid. Each baseline gives every snapshot a score in 0-1.
"""

import random
from collections.abc import Callable

from riskdetect.features import FeatureRow

Baseline = Callable[[FeatureRow], float]


def age_only(row: FeatureRow) -> float:
    """Newer accounts score higher. The unfair shortcut."""
    age = row.get("account_age_days")
    return 1.0 if age is None else 1.0 / (1.0 + max(float(age), 0.0))


def volume_only(row: FeatureRow) -> float:
    """Busier users score higher."""
    pct = row.get("posts_24h_pct")
    return 0.0 if pct is None else float(pct) / 100.0


def random_baseline(seed: int = 0) -> Baseline:
    rng = random.Random(seed)
    return lambda row: rng.random()


def baselines(seed: int = 0) -> dict[str, Baseline]:
    return {
        "random": random_baseline(seed),
        "age_only": age_only,
        "volume_only": volume_only,
    }
