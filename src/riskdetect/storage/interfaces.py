"""What each store can do, independent of how it is done.

The rest of the system depends on these interfaces only. The v1 implementation
uses Parquet files queried with DuckDB; a database-backed store could replace it
later without changing any other package (see ADR 005).
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from riskdetect.schema import Event, Rejection


class EventStore(Protocol):
    def append(self, events: list[Event]) -> int:
        """Save events. Events are never edited afterwards (append-only)."""
        ...

    def exists(self, event_ids: Iterable[str]) -> set[str]:
        """Which of these IDs are already stored (used for deduplication)."""
        ...

    def get_actor_events(
        self,
        platform: str,
        actor_id: str,
        *,
        until: datetime | None = None,
        since: datetime | None = None,
    ) -> list[Event]:
        """One actor's events in time order, with ``since <= occurred_at < until``.

        ``until`` is exclusive: features computed "as of t" must only see events
        that happened strictly before t. This is the main guard against leakage.
        """
        ...

    def iter_events(
        self,
        platform: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator[Event]:
        """Events with ``start <= occurred_at < end`` (optionally one platform), in time order."""
        ...

    def count(self, platform: str | None = None) -> int: ...

    def max_occurred_at(self, platform: str) -> datetime | None:
        """Time of the newest stored event for a platform (the ingestion watermark)."""
        ...

    def delete_actor(self, platform: str, actor_id: str) -> int:
        """Remove all of one actor's events (privacy requests). Returns how many."""
        ...


@dataclass(frozen=True)
class QuarantinedRecord:
    platform: str
    quarantined_at: datetime
    rejection: Rejection


class QuarantineStore(Protocol):
    def append(self, platform: str, rejections: list[Rejection], at: datetime) -> int: ...

    def read(self, platform: str | None = None) -> list[QuarantinedRecord]: ...
