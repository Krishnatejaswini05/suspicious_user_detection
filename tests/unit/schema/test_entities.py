from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from riskdetect.schema import Actor, Label, LabelCategory, LabelSource, Space, SpaceKind

T0 = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


def test_actor_defaults_and_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    actor = Actor(
        actor_id="U17",
        platform="synthetic_forum",
        created_at=datetime(2026, 10, 2, 15, 30, tzinfo=ist),
    )
    assert actor.created_at == T0
    assert not actor.is_verified
    assert not actor.is_allowlisted


def test_space_default_kind() -> None:
    assert Space(space_id="electronics", platform="synthetic_market").kind is SpaceKind.OTHER


class TestLabel:
    def test_bad_actor_label(self) -> None:
        label = Label(
            actor_id="S42",
            platform="synthetic_market",
            category=LabelCategory.SPAM,
            abuse_start=T0,
            decided_at=T0 + timedelta(hours=1),
            source=LabelSource.SYNTHETIC,
        )
        assert label.confidence == 1.0

    def test_clean_label_cannot_have_abuse_start(self) -> None:
        with pytest.raises(ValidationError, match="clean label"):
            Label(
                actor_id="U17",
                platform="synthetic_forum",
                category=LabelCategory.CLEAN,
                abuse_start=T0,
                decided_at=T0,
                source=LabelSource.REVIEWER,
            )

    def test_abuse_cannot_start_after_decision(self) -> None:
        with pytest.raises(ValidationError, match="abuse_start"):
            Label(
                actor_id="S42",
                platform="synthetic_market",
                category=LabelCategory.SPAM,
                abuse_start=T0 + timedelta(days=1),
                decided_at=T0,
                source=LabelSource.MODERATOR,
            )

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_confidence_range(self, confidence: float) -> None:
        with pytest.raises(ValidationError):
            Label(
                actor_id="S42",
                platform="synthetic_market",
                category=LabelCategory.SPAM,
                decided_at=T0,
                source=LabelSource.CONTENT_REMOVAL,
                confidence=confidence,
            )
