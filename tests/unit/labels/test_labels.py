from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from riskdetect.labels import ActorTruth, Outcome, known_by, label_rows, snapshot_outcome
from riskdetect.schema import Label, LabelCategory, LabelSource

T0 = datetime(2026, 8, 10, tzinfo=UTC)


def label(category: str = "spam", abuse_start: datetime | None = T0, **extra: Any) -> Label:
    data: dict[str, Any] = {
        "actor_id": "u1",
        "platform": "synthetic_forum",
        "category": category,
        "decided_at": T0 + timedelta(days=5),
        "source": "synthetic",
        "abuse_start": abuse_start if category != "clean" else None,
    }
    data.update(extra)
    return Label.model_validate(data)


class TestSnapshotOutcome:
    def test_clean_is_negative(self) -> None:
        assert snapshot_outcome(label("clean"), T0) is Outcome.NEGATIVE

    def test_after_abuse_began_is_positive(self) -> None:
        assert snapshot_outcome(label(), T0 + timedelta(hours=1)) is Outcome.POSITIVE

    def test_before_abuse_began_is_excluded(self) -> None:
        assert snapshot_outcome(label(), T0 - timedelta(days=1)) is Outcome.EXCLUDED

    def test_horizon_counts_abuse_starting_soon(self) -> None:
        early = T0 - timedelta(hours=6)
        assert snapshot_outcome(label(), early, horizon=timedelta(days=1)) is Outcome.POSITIVE

    def test_bad_without_known_start_is_always_positive(self) -> None:
        assert snapshot_outcome(label(abuse_start=None), T0) is Outcome.POSITIVE

    def test_no_label_is_unlabeled(self) -> None:
        assert snapshot_outcome(None, T0) is Outcome.UNLABELED


def test_known_by_hides_later_decisions() -> None:
    early = label(decided_at=T0 + timedelta(days=1))
    late = label(decided_at=T0 + timedelta(days=9))
    assert known_by([early, late], T0 + timedelta(days=2)) == [early]


def test_label_rows() -> None:
    truths = {
        ("synthetic_forum", "bad"): ActorTruth("synthetic_forum", "bad", label(), "spam_bot"),
        ("synthetic_forum", "good"): ActorTruth(
            "synthetic_forum", "good", label("clean", confidence=0.9), "normal"
        ),
    }

    def row(actor: str, as_of: datetime) -> dict[str, Any]:
        return {"platform": "synthetic_forum", "actor_id": actor, "as_of": as_of}

    labeled = label_rows(
        [
            row("bad", T0 - timedelta(days=1)),  # before abuse: dropped
            row("bad", T0 + timedelta(days=1)),
            row("good", T0),
            row("stranger", T0),
        ],
        truths,
        unlabeled_weight=0.25,
    )
    assert [(r.row["actor_id"], r.y, r.weight, r.segment) for r in labeled] == [
        ("bad", 1, 1.0, "spam_bot"),
        ("good", 0, 0.9, "normal"),
        ("stranger", 0, 0.25, None),
    ]
    assert labeled[2].outcome is Outcome.UNLABELED


def test_label_category_enum_is_used() -> None:
    assert label("bot").category is LabelCategory.BOT
    assert label().source is LabelSource.SYNTHETIC
    with pytest.raises(ValueError):
        label("clean", abuse_start=None, confidence=2.0)
