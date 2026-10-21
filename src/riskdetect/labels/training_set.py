"""Join feature snapshots with the right answers, ready for marking or training."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from riskdetect.features import FeatureRow
from riskdetect.labels.outcomes import Outcome, TruthIndex, snapshot_outcome

DEFAULT_UNLABELED_WEIGHT = 0.3


@dataclass(frozen=True)
class LabeledRow:
    row: FeatureRow
    outcome: Outcome
    weight: float  # how much to trust this answer (label confidence, or low if unlabeled)
    segment: str | None

    @property
    def y(self) -> int:
        """1 for "should be flagged", 0 otherwise."""
        return 1 if self.outcome is Outcome.POSITIVE else 0


def label_rows(
    rows: Iterable[FeatureRow],
    truths: TruthIndex,
    *,
    horizon: timedelta = timedelta(0),
    unlabeled_weight: float = DEFAULT_UNLABELED_WEIGHT,
) -> list[LabeledRow]:
    """Attach outcomes to feature rows, dropping EXCLUDED snapshots."""
    labeled = []
    for row in rows:
        truth = truths.get((row["platform"], row["actor_id"]))
        label = truth.label if truth else None
        outcome = snapshot_outcome(label, row["as_of"], horizon)
        if outcome is Outcome.EXCLUDED:
            continue
        weight = label.confidence if label is not None else unlabeled_weight
        labeled.append(LabeledRow(row, outcome, weight, truth.segment if truth else None))
    return labeled
