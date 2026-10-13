"""The single front door for events.

For each batch of adapter results:
1. Rejections go to quarantine, with their reasons.
2. Events are deduplicated (within the batch and against storage).
3. New events are stamped with ``ingested_at``.
4. Late arrivals are counted and their actors marked for rescoring.
5. New events are stored.
6. New events are published to whoever is listening (realtime/, later).
"""

from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from itertools import islice

from riskdetect.ingestion.dedupe import split_new
from riskdetect.ingestion.lateness import DEFAULT_VERY_LATE_AFTER, check_lateness
from riskdetect.ingestion.publisher import NullPublisher, Publisher
from riskdetect.ingestion.report import IngestReport
from riskdetect.schema import Event, Rejection
from riskdetect.storage import EventStore, QuarantineStore

DEFAULT_BATCH_SIZE = 50_000


def _batched(items: Iterable[Event | Rejection], size: int) -> Iterator[list[Event | Rejection]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


class IngestionPipeline:
    def __init__(
        self,
        events: EventStore,
        quarantine: QuarantineStore,
        publisher: Publisher | None = None,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        very_late_after: timedelta = DEFAULT_VERY_LATE_AFTER,
    ) -> None:
        self.events = events
        self.quarantine = quarantine
        self.publisher = publisher or NullPublisher()
        self.batch_size = batch_size
        self.clock = clock
        self.very_late_after = very_late_after

    def ingest(self, platform: str, results: Iterable[Event | Rejection]) -> IngestReport:
        """Ingest one platform's adapter output, in batches. Safe to repeat."""
        report = IngestReport(platform)
        # Measured once, before this load: events from this load are never "late" relative
        # to each other, only relative to what was already stored.
        watermark = self.events.max_occurred_at(platform)
        for batch in _batched(results, self.batch_size):
            self._ingest_batch(platform, batch, watermark, report)
        return report

    def _ingest_batch(
        self,
        platform: str,
        batch: list[Event | Rejection],
        watermark: datetime | None,
        report: IngestReport,
    ) -> None:
        now = self.clock()
        report.received += len(batch)

        rejections = [item for item in batch if isinstance(item, Rejection)]
        if rejections:
            self.quarantine.append(platform, rejections, now)
            report.rejections.update(r.reason for r in rejections)

        events = [item for item in batch if isinstance(item, Event)]
        wrong = {e.platform for e in events} - {platform}
        if wrong:
            raise ValueError(f"ingesting {platform!r} but got events for {sorted(wrong)}")

        new, duplicates = split_new(events, self.events)
        report.duplicates += duplicates
        if not new:
            return
        stamped = [e if e.ingested_at else e.model_copy(update={"ingested_at": now}) for e in new]

        lateness = check_lateness(stamped, watermark, self.very_late_after)
        report.late += lateness.late
        report.very_late += lateness.very_late
        report.actors_to_rescore |= lateness.actors_to_rescore

        report.stored += self.events.append(stamped)
        self.publisher.publish(stamped)
        report.published += len(stamped)
