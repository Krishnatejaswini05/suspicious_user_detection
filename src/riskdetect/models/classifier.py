"""The supervised model: "does this user behave like known abusive accounts?"

Boosted trees learn from labeled snapshots, then an isotonic calibrator (fitted on
the *last* days of the training period, which the trees did not see) turns raw
scores into honest probabilities.

Fairness: the model never sees lifecycle or evidence features (account age,
how much history we have, how many events we have seen). Those describe how long
someone has been around, not how they behave. Evidence volume still drives
*confidence* in scoring, as before. Count features are used as per-platform
percentiles, so one model can serve every platform.

Trust: on platforms it learned (and was calibrated) on, a confident model may
escalate on its own. On a platform it has never seen, it is advisory only (a weak
signal) until that platform has labels of its own: the platform hold-out test showed
confident mistakes on ordinary users of an unseen platform.
"""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from riskdetect.features import PCT_SUFFIX, FeatureRow, all_features
from riskdetect.labels import TruthIndex, label_rows
from riskdetect.models.calibration import IsotonicCalibrator
from riskdetect.models.gbdt import BoostingParams, GradientBoostedTrees
from riskdetect.scoring.evidence import Signal

CODE = "M003_learned_model"
WEAK_FROM = 0.5  # calibrated probability from which the model speaks at all
# ...and from which it can escalate on its own. Set high on purpose: trained on simulated
# data, the model can learn habits of the simulator (e.g. "always the same site" = spam)
# rather than of spammers, so alone it only sends a user to a person when very sure.
STRONG_FROM = 0.9
# Behavior can't be judged from a couple of posts: below this many posts in the past
# week the model stays silent (the live replay showed ratios over 2-4 posts misread).
MIN_POSTS_7D = 5
_NOT_BEHAVIOR = frozenset({"lifecycle", "evidence"})
_NOT_BEHAVIOR_NAMES = frozenset({"history_days"})


def classifier_features() -> tuple[str, ...]:
    """Behavior features only, with counts as percentiles."""
    names = []
    for feature in all_features():
        if feature.family in _NOT_BEHAVIOR or feature.name in _NOT_BEHAVIOR_NAMES:
            continue
        names.append(feature.name + PCT_SUFFIX if feature.percentile else feature.name)
    return tuple(names)


def _readable(name: str) -> str:
    base = name.removesuffix(PCT_SUFFIX).replace("_", " ")
    return f"{base} (percentile)" if name.endswith(PCT_SUFFIX) else base


class SupervisedClassifier:
    name = "classifier"

    def __init__(
        self,
        model: GradientBoostedTrees,
        calibrator: IsotonicCalibrator,
        features: tuple[str, ...],
        trained_platforms: frozenset[str] = frozenset(),
    ) -> None:
        self.model = model
        self.calibrator = calibrator
        self.features = features
        self.trained_platforms = trained_platforms

    def vector(self, row: Mapping[str, Any]) -> list[float | None]:
        return [None if row.get(f) is None else float(row[f]) for f in self.features]

    def probability(self, row: Mapping[str, Any]) -> float:
        return self.calibrator(self.model.predict_proba(self.vector(row)))

    def top_factors(self, row: Mapping[str, Any], top: int = 3) -> list[tuple[str, float]]:
        """The features that pushed this user's score up the most, with their values."""
        vector = self.vector(row)
        contributions = self.model.contributions(vector)
        ranked = sorted(range(len(vector)), key=lambda i: -contributions[i])
        return [
            (self.features[i], vector[i])  # type: ignore[misc]
            for i in ranked[:top]
            if contributions[i] > 0 and vector[i] is not None
        ]

    def signals(self, row: Mapping[str, Any]) -> list[Signal]:
        posts = row.get("posts_7d")
        if posts is None or float(posts) < MIN_POSTS_7D:
            return []
        probability = self.probability(row)
        if probability < WEAK_FROM:
            return []
        factors = self.top_factors(row)
        detail = ", ".join(f"{_readable(name)} {value:.2f}" for name, value in factors)
        known_platform = row["platform"] in self.trained_platforms
        note = "" if known_platform else " (advisory: not yet trained on this platform)"
        return [
            Signal(
                code=CODE,
                source=f"model:{self.name}",
                category="learned",
                strength=round(min(probability, 0.95), 4),
                strong=known_platform and probability >= STRONG_FROM,
                reason=f"Behaves like known abusive accounts (learned model, probability "
                f"{probability:.2f}){note}" + (f"; strongest factors: {detail}" if detail else ""),
                evidence={"probability": round(probability, 4), **dict(factors)},
            )
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": list(self.features),
            "trained_platforms": sorted(self.trained_platforms),
            "model": self.model.to_dict(),
            "calibrator": self.calibrator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SupervisedClassifier":
        features = tuple(data["features"])
        if features != classifier_features():
            raise ValueError("saved classifier uses a different feature list; retrain it")
        return cls(
            GradientBoostedTrees.from_dict(data["model"]),
            IsotonicCalibrator.from_dict(data["calibrator"]),
            features,
            frozenset(data["trained_platforms"]),
        )


def train_classifier(
    rows: Sequence[FeatureRow],
    truths: TruthIndex,
    *,
    calibration_days: int = 4,
    params: BoostingParams | None = None,
) -> SupervisedClassifier:
    """Train on labeled snapshots; calibrate on the last ``calibration_days`` of them.

    ``rows`` must come from the training period only, with percentile columns.
    """
    labeled = label_rows(rows, truths)
    if not labeled:
        raise ValueError("no labeled snapshots to train on")
    latest = max(item.row["as_of"] for item in labeled)
    cutoff = latest - timedelta(days=calibration_days - 1)
    fit = [item for item in labeled if item.row["as_of"] < cutoff]
    held = [item for item in labeled if item.row["as_of"] >= cutoff]
    if len({i.y for i in fit}) < 2 or len({i.y for i in held}) < 2:
        fit = held = labeled  # too little data to hold some back; calibration is optimistic

    features = classifier_features()
    model = GradientBoostedTrees(params).fit(
        [[None if i.row.get(f) is None else float(i.row[f]) for f in features] for i in fit],
        [i.y for i in fit],
        [i.weight for i in fit],
    )
    raw = [
        model.predict_proba([None if i.row.get(f) is None else float(i.row[f]) for f in features])
        for i in held
    ]
    calibrator = IsotonicCalibrator().fit(raw, [i.y for i in held], [i.weight for i in held])
    platforms = frozenset(i.row["platform"] for i in held if i.y)  # calibrated with real positives
    return SupervisedClassifier(model, calibrator, features, platforms)
