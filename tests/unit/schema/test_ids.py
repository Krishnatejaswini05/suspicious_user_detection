from datetime import UTC, datetime, timedelta, timezone

import pytest

from riskdetect.schema import EventType, derived_event_id, scoped_event_id

T0 = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


def derive(**overrides: object) -> str:
    args: dict[str, object] = {
        "platform": "synthetic_chat",
        "actor_id": "S42",
        "event_type": EventType.CONTENT_CREATED,
        "occurred_at": T0,
        "source_position": "export.csv#1",
        "text_hash": "a" * 64,
    }
    args.update(overrides)
    return derived_event_id(**args)  # type: ignore[arg-type]


def test_scoped_id() -> None:
    assert scoped_event_id("synthetic_market", "post_123") == "synthetic_market:post_123"
    with pytest.raises(ValueError):
        scoped_event_id("synthetic_market", "")


def test_derived_id_is_deterministic() -> None:
    # Reloading the same file must give the same ID, so dedupe works.
    assert derive() == derive()
    assert derive().startswith("synthetic_chat:d:")


def test_derived_id_ignores_timezone_representation() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    assert derive(occurred_at=T0.astimezone(ist)) == derive()


def test_identical_actions_at_same_instant_get_different_ids() -> None:
    # A bot double-posting the same text in the same second is two real events.
    assert derive(source_position="export.csv#1") != derive(source_position="export.csv#2")


@pytest.mark.parametrize(
    "change",
    [
        {"actor_id": "S43"},
        {"platform": "synthetic_forum"},
        {"event_type": EventType.CONTENT_EDITED},
        {"occurred_at": T0 + timedelta(microseconds=1)},
        {"target_id": "p1"},
        {"text_hash": "b" * 64},
    ],
)
def test_any_detail_change_changes_id(change: dict[str, object]) -> None:
    assert derive(**change) != derive()


def test_derived_id_requires_position_and_aware_time() -> None:
    with pytest.raises(ValueError):
        derive(source_position="")
    with pytest.raises(ValueError):
        derive(occurred_at=datetime(2026, 10, 2, 10, 0))
