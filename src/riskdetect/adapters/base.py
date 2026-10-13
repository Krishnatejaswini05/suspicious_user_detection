"""What every adapter must provide, generic or custom.

The rest of the system only talks to this interface, so a custom adapter for an
unusual source plugs in exactly like the generic one.
"""

from collections.abc import Iterable, Iterator
from typing import Protocol

from riskdetect.adapters.readers import RawRecord
from riskdetect.adapters.report import MappingReport
from riskdetect.schema import Event, Rejection

AdapterResult = Event | Rejection


class PlatformAdapter(Protocol):
    platform: str

    def read(self) -> Iterator[RawRecord]:
        """Raw records from the platform's source, uninterpreted."""
        ...

    def to_events(self, record: RawRecord) -> list[AdapterResult]:
        """Translate one raw record into zero or more Events (or Rejections)."""
        ...

    def new_report(self) -> MappingReport:
        """An empty report configured for this adapter's columns."""
        ...


def run_adapter(
    adapter: PlatformAdapter,
    report: MappingReport,
    records: Iterable[RawRecord] | None = None,
) -> Iterator[AdapterResult]:
    """Translate records (by default, everything ``adapter.read()`` yields), filling ``report``."""
    for record in adapter.read() if records is None else records:
        results = adapter.to_events(record)
        report.add(record, results)
        yield from results
