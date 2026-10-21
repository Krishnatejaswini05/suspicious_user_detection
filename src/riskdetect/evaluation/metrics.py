"""Accuracy numbers, computed from (score, flagged, truth) triples.

- precision: of the snapshots we flagged, the share that were really bad;
- recall: of the really bad snapshots, the share we flagged;
- false positive rate: of the innocent snapshots, the share we wrongly flagged;
- average precision: one number for the whole ranking (1.0 = every bad snapshot
  ranked above every innocent one), independent of any single threshold;
- precision@k: if reviewers can check k cases, how many of our top k are really bad.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import groupby


@dataclass(frozen=True)
class Scored:
    score: float
    flagged: bool
    y: int  # 1 = should be flagged


@dataclass(frozen=True)
class Metrics:
    n: int
    positives: int
    negatives: int
    true_positives: int
    false_positives: int
    precision: float | None
    recall: float | None
    false_positive_rate: float | None
    average_precision: float | None
    precision_at_k: dict[int, float] = field(default_factory=dict)

    @property
    def flagged(self) -> int:
        return self.true_positives + self.false_positives


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def average_precision(items: Sequence[Scored]) -> float | None:
    """Area under the precision-recall curve; tied scores are treated as one step."""
    positives = sum(item.y for item in items)
    if positives == 0:
        return None
    ranked = sorted(items, key=lambda item: -item.score)
    tp = fp = 0
    total = 0.0
    for _, group in groupby(ranked, key=lambda item: item.score):
        members = list(group)
        hits = sum(item.y for item in members)
        tp += hits
        fp += len(members) - hits
        total += (hits / positives) * (tp / (tp + fp))
    return total


def precision_at(items: Sequence[Scored], k: int) -> float | None:
    if not items:
        return None
    top = sorted(items, key=lambda item: -item.score)[:k]
    return sum(item.y for item in top) / len(top)


def compute_metrics(items: Sequence[Scored], ks: Sequence[int] = (10, 50, 100)) -> Metrics:
    positives = sum(item.y for item in items)
    negatives = len(items) - positives
    tp = sum(1 for item in items if item.flagged and item.y)
    fp = sum(1 for item in items if item.flagged and not item.y)
    at_k = {}
    for k in ks:
        value = precision_at(items, k)
        if value is not None:
            at_k[k] = value
    return Metrics(
        n=len(items),
        positives=positives,
        negatives=negatives,
        true_positives=tp,
        false_positives=fp,
        precision=_ratio(tp, tp + fp),
        recall=_ratio(tp, positives),
        false_positive_rate=_ratio(fp, negatives),
        average_precision=average_precision(items),
        precision_at_k=at_k,
    )
