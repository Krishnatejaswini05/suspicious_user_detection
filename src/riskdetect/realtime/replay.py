"""Replay stored events through the live desk, as if they were happening now.

Used to measure how quickly abuse would have been caught live, and to compare
live results with the nightly batch.
"""

from datetime import datetime

from riskdetect.realtime.processor import RealtimeProcessor
from riskdetect.storage import EventStore


def replay(
    store: EventStore,
    platform: str,
    processor: RealtimeProcessor,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    flush: bool = True,
    score_from: datetime | None = None,
) -> int:
    """Feed a platform's stored events, in time order, into ``processor``. Returns events fed.

    Events before ``score_from`` only build up history (no scoring), like connecting a
    platform: load its history first, then go live.
    """
    count = 0
    for event in store.iter_events(platform, start=start, end=end):
        if score_from is not None and event.occurred_at < score_from:
            processor.observe(event)
        else:
            processor.process(event)
        count += 1
    if flush:
        processor.flush()
    return count
