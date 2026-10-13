"""Turning untrusted input into Events, or into Rejections with a reason.

Structural rules (required fields, allowed blocks, UTC timestamps) live on the
Event model itself. This module adds checks that depend on context, such as the
current time, and converts every failure into a Rejection so that bad events are
quarantined with a reason instead of being silently dropped.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from riskdetect.schema.events import Event
from riskdetect.schema.version import SUPPORTED_SCHEMA_VERSIONS

DEFAULT_MAX_CLOCK_SKEW = timedelta(minutes=5)


class RejectionReason(StrEnum):
    INVALID_STRUCTURE = "invalid_structure"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    FUTURE_TIMESTAMP = "future_timestamp"
    # Raised by adapters, before an Event can be built.
    UNMAPPED_ACTION = "unmapped_action"
    INVALID_TIMESTAMP = "invalid_timestamp"


@dataclass(frozen=True, slots=True)
class Rejection:
    """Why an input could not become an Event. Stored in quarantine for later repair."""

    reason: RejectionReason
    detail: str
    fields: tuple[str, ...] = ()
    raw: Mapping[str, Any] | None = None


def check_event(
    event: Event,
    *,
    now: datetime | None = None,
    max_clock_skew: timedelta = DEFAULT_MAX_CLOCK_SKEW,
) -> Rejection | None:
    """Context-dependent checks on an already well-formed Event."""
    if event.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return Rejection(
            RejectionReason.UNSUPPORTED_SCHEMA_VERSION,
            f"schema_version {event.schema_version} is not supported",
            ("schema_version",),
        )
    reference = now if now is not None else datetime.now(UTC)
    if event.occurred_at > reference + max_clock_skew:
        return Rejection(
            RejectionReason.FUTURE_TIMESTAMP,
            f"occurred_at {event.occurred_at.isoformat()} is in the future",
            ("occurred_at",),
        )
    if event.ingested_at is not None and event.occurred_at > event.ingested_at + max_clock_skew:
        return Rejection(
            RejectionReason.FUTURE_TIMESTAMP,
            "occurred_at is later than ingested_at",
            ("occurred_at", "ingested_at"),
        )
    return None


def parse_event(
    data: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_clock_skew: timedelta = DEFAULT_MAX_CLOCK_SKEW,
) -> Event | Rejection:
    """Build an Event from untrusted data, or explain why it was rejected."""
    try:
        event = Event.model_validate(data)
    except ValidationError as exc:
        problems = [
            (".".join(str(part) for part in err["loc"]) or "<event>", err["msg"])
            for err in exc.errors()
        ]
        fields = tuple(dict.fromkeys(location for location, _ in problems))
        detail = "; ".join(f"{location}: {message}" for location, message in problems)
        return Rejection(RejectionReason.INVALID_STRUCTURE, detail, fields, dict(data))

    rejection = check_event(event, now=now, max_clock_skew=max_clock_skew)
    if rejection is not None:
        return replace(rejection, raw=dict(data))
    return event
