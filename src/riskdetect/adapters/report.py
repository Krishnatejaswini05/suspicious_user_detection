"""Mapping report: what happened when a platform's data was translated.

Shows how many records became events, why the rest were rejected, and which
canonical fields actually have data. ``available_fields`` later drives automatic
feature selection (no text on a platform -> content features switched off).
"""

from collections import Counter
from dataclasses import dataclass, field

from riskdetect.adapters.readers import RawRecord
from riskdetect.schema import Event, EventType, Rejection, RejectionReason

_EVENT_FAMILIES: dict[str, frozenset[EventType]] = {
    "content": frozenset(
        {EventType.CONTENT_CREATED, EventType.CONTENT_EDITED, EventType.CONTENT_DELETED}
    ),
    "interactions": frozenset({EventType.INTERACTION}),
    "reports": frozenset({EventType.REPORT_FILED}),
    "moderation": frozenset({EventType.MODERATION_ACTION}),
}


@dataclass
class MappingReport:
    platform: str
    # Canonical field name -> raw column it is read from.
    columns: dict[str, str] = field(default_factory=dict)
    records_read: int = 0
    events_produced: int = 0
    rejections: Counter[RejectionReason] = field(default_factory=Counter)
    event_types: Counter[EventType] = field(default_factory=Counter)
    non_null: Counter[str] = field(default_factory=Counter)
    seen_columns: set[str] = field(default_factory=set)

    def add(self, record: RawRecord, results: list[Event | Rejection]) -> None:
        self.records_read += 1
        self.seen_columns.update(record.data)
        for name, column in self.columns.items():
            if record.data.get(column) is not None:
                self.non_null[name] += 1
        for result in results:
            if isinstance(result, Event):
                self.events_produced += 1
                self.event_types[result.event_type] += 1
            else:
                self.rejections[result.reason] += 1

    @property
    def rejected(self) -> int:
        return sum(self.rejections.values())

    @property
    def missing_columns(self) -> list[str]:
        """Configured columns that never appeared in the data (likely a mapping mistake)."""
        if not self.records_read:
            return []
        return sorted({c for c in self.columns.values() if c not in self.seen_columns})

    def coverage(self, name: str) -> float:
        """Share of records with a value for a canonical field."""
        return self.non_null[name] / self.records_read if self.records_read else 0.0

    @property
    def available_fields(self) -> list[str]:
        """Canonical fields and event families that actually have data on this platform."""
        fields = {name for name in self.columns if self.non_null[name] > 0}
        fields.discard("action")
        for family, types in _EVENT_FAMILIES.items():
            if any(self.event_types[t] for t in types):
                fields.add(family)
        return sorted(fields)

    @property
    def unavailable_fields(self) -> list[str]:
        known = {"space_id", "text", "urls", "language", "target_id", "target_owner_id"}
        known |= set(_EVENT_FAMILIES)
        return sorted(known - set(self.available_fields))

    def summary(self) -> str:
        lines = [
            f"Platform:          {self.platform}",
            f"Records read:      {self.records_read:,}",
            f"Events produced:   {self.events_produced:,}",
            f"Rejected:          {self.rejected:,}",
        ]
        for reason, count in self.rejections.most_common():
            lines.append(f"  {reason}: {count:,}")
        lines.append(f"Fields available:  {', '.join(self.available_fields) or '-'}")
        lines.append(f"Fields missing:    {', '.join(self.unavailable_fields) or '-'}")
        if self.missing_columns:
            lines.append(f"WARNING columns never seen in data: {', '.join(self.missing_columns)}")
        return "\n".join(lines)
