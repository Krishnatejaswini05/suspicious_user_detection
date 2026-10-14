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
) -> int:
    """Feed a platform's stored events, in time order, into ``processor``. Returns events fed."""
    count = 0
    for event in store.iter_events(platform, start=start, end=end):
        processor.process(event)
        count += 1
    if flush:
        processor.flush()
    return count
