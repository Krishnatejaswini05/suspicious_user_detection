from datetime import UTC, datetime, timedelta
from typing import Any

from riskdetect.schema import (
    Event,
    Rejection,
    RejectionReason,
    check_event,
    parse_event,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def raw(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "event_id": "synthetic_forum:p1",
        "platform": "synthetic_forum",
        "actor_id": "U17",
        "event_type": "CONTENT_CREATED",
        "occurred_at": "2026-10-12T11:00:00Z",
        "content": {"kind": "post"},
    }
    data.update(overrides)
    return data


def test_valid_input_becomes_event() -> None:
    assert isinstance(parse_event(raw(), now=NOW), Event)


def test_structural_problem_is_rejected_with_reason_and_raw() -> None:
    data = raw()
    del data["actor_id"]
    result = parse_event(data, now=NOW)
    assert isinstance(result, Rejection)
    assert result.reason is RejectionReason.INVALID_STRUCTURE
    assert "actor_id" in result.fields
    assert "actor_id" in result.detail
    assert result.raw == data  # kept for quarantine and later repair


def test_block_rule_violation_is_reported() -> None:
    result = parse_event(raw(content=None), now=NOW)
    assert isinstance(result, Rejection)
    assert "requires 'content'" in result.detail


def test_future_timestamp_is_rejected() -> None:
    result = parse_event(raw(occurred_at="2026-10-12T13:00:00Z"), now=NOW)
    assert isinstance(result, Rejection)
    assert result.reason is RejectionReason.FUTURE_TIMESTAMP
    assert result.raw is not None


def test_small_clock_skew_is_tolerated() -> None:
    slightly_ahead = (NOW + timedelta(minutes=2)).isoformat()
    assert isinstance(parse_event(raw(occurred_at=slightly_ahead), now=NOW), Event)


def test_occurred_after_ingested_is_rejected() -> None:
    result = parse_event(
        raw(occurred_at="2026-10-12T11:00:00Z", ingested_at="2026-10-12T10:00:00Z"), now=NOW
    )
    assert isinstance(result, Rejection)
    assert result.reason is RejectionReason.FUTURE_TIMESTAMP


def test_unsupported_schema_version_is_rejected() -> None:
    result = parse_event(raw(schema_version=99), now=NOW)
    assert isinstance(result, Rejection)
    assert result.reason is RejectionReason.UNSUPPORTED_SCHEMA_VERSION


def test_check_event_passes_good_event() -> None:
    event = Event.model_validate(raw())
    assert check_event(event, now=NOW) is None
