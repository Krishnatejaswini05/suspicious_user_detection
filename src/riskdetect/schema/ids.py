"""Event ID construction.

Event IDs drive deduplication, so they must be stable: the same real-world event
must always get the same ID, and two different events must never share one.

- Prefer the platform's own ID (post ID, message ID): ``scoped_event_id``.
- Only when the source has no ID, derive one from the event's details plus its
  position in the source (``derived_event_id``). The position keeps two identical
  actions in the same instant (e.g. a bot double-posting) from collapsing into one.
"""

import hashlib
from datetime import datetime

from riskdetect.schema.enums import EventType
from riskdetect.schema.events import to_utc

_SEPARATOR = "\x1f"  # ASCII unit separator; cannot appear in normal field values


def scoped_event_id(platform: str, native_id: str) -> str:
    """ID from the platform's own identifier, scoped so platforms cannot collide."""
    if not native_id:
        raise ValueError("native_id must be non-empty")
    return f"{platform}:{native_id}"


def derived_event_id(
    *,
    platform: str,
    actor_id: str,
    event_type: EventType,
    occurred_at: datetime,
    source_position: str,
    target_id: str | None = None,
    text_hash: str | None = None,
) -> str:
    """Deterministic ID for sources that provide none.

    ``source_position`` identifies where the record came from, e.g. ``"export.csv#1042"``.
    Reloading the same file yields the same IDs, so reloads deduplicate correctly.
    """
    if not source_position:
        raise ValueError("source_position must be non-empty")
    parts = (
        platform,
        actor_id,
        str(event_type),
        to_utc(occurred_at).isoformat(timespec="microseconds"),
        target_id or "",
        text_hash or "",
        source_position,
    )
    digest = hashlib.sha256(_SEPARATOR.join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{platform}:d:{digest}"
