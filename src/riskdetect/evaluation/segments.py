"""Fairness: results per group of users.

An overall false-alarm rate can hide unfairness, so it is broken down by group.
The most important group is new accounts: they must not be flagged more often
than everyone else.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from riskdetect.evaluation.metrics import Scored
from riskdetect.labels import LabeledRow

NEW_ACCOUNT_DAYS = 7
NEW_ACCOUNTS = "account: new (< 7 days)"


@dataclass(frozen=True)
class SegmentRate:
    segment: str
    negatives: int
    false_positives: int

    @property
    def false_positive_rate(self) -> float | None:
        return None if self.negatives == 0 else self.false_positives / self.negatives


def segments_of(item: LabeledRow) -> list[str]:
    row = item.row
    names = [f"platform: {row['platform']}"]
    age = row.get("account_age_days")
    if age is not None:
        names.append(NEW_ACCOUNTS if age < NEW_ACCOUNT_DAYS else "account: established")
    seen = row.get("events_seen") or 0
    names.append(
        "activity: low (< 20 events)"
        if seen < 20
        else "activity: high (500+ events)"
        if seen >= 500
        else "activity: medium"
    )
    if item.segment:
        names.append(f"group: {item.segment}")
    return names


def false_positive_rates(
    labeled: Sequence[LabeledRow], scored: Sequence[Scored]
) -> list[SegmentRate]:
    """False-alarm rate among innocent snapshots, per segment."""
    negatives: dict[str, int] = defaultdict(int)
    false_positives: dict[str, int] = defaultdict(int)
    for item, result in zip(labeled, scored, strict=True):
        if result.y:
            continue
        for name in segments_of(item):
            negatives[name] += 1
            false_positives[name] += int(result.flagged)
    return [SegmentRate(n, negatives[n], false_positives[n]) for n in sorted(negatives)]


def rate_for(rates: Iterable[SegmentRate], segment: str) -> SegmentRate | None:
    return next((rate for rate in rates if rate.segment == segment), None)
