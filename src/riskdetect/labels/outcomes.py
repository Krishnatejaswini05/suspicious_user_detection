"""What the right answer is for one user at one moment.

A label says who someone really is (spam bot, clean, ...) and when their abuse
began. A *snapshot* of that user at time t then has an outcome:

- POSITIVE: abuse had begun by t (+ an optional horizon), so a detector should flag it.
- NEGATIVE: the user is clean, so a flag is a false alarm.
- EXCLUDED: a bad user whose abuse had not begun yet. They are neither guilty nor
  innocent at that moment, so the snapshot is left out of marking.
- UNLABELED: nobody has decided about this user (common on real platforms). Treated
  as probably clean, with less weight, never as certainly clean.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from riskdetect.schema import Label, LabelCategory


class Outcome(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    EXCLUDED = "excluded"
    UNLABELED = "unlabeled"


@dataclass(frozen=True)
class ActorTruth:
    """Everything known about one user's true nature."""

    platform: str
    actor_id: str
    label: Label | None
    # A free-form group for reporting, e.g. the simulator's persona ("spam_bot").
    segment: str | None = None


def snapshot_outcome(
    label: Label | None, as_of: datetime, horizon: timedelta = timedelta(0)
) -> Outcome:
    """The outcome for a snapshot taken at ``as_of``.

    ``horizon`` > 0 also counts abuse that begins shortly *after* the snapshot as
    positive, for training an early-warning model. Detection uses 0.
    """
    if label is None:
        return Outcome.UNLABELED
    if label.category is LabelCategory.CLEAN:
        return Outcome.NEGATIVE
    if label.abuse_start is None or label.abuse_start <= as_of + horizon:
        return Outcome.POSITIVE
    return Outcome.EXCLUDED


def known_by(labels: Iterable[Label], cutoff: datetime) -> list[Label]:
    """Labels that had been decided by ``cutoff``.

    Training must only use answers that were known at training time; otherwise the
    model learns from decisions that had not been made yet (leakage).
    """
    return [label for label in labels if label.decided_at <= cutoff]


TruthIndex = dict[tuple[str, str], ActorTruth]  # (platform, actor_id) -> truth
