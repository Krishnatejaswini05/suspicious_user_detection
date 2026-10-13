"""Spot events that arrive late or out of order.

The *watermark* is the time of the newest event already stored for a platform
before this load. An event older than the watermark is late: it changes the past
for its actor, so that actor must be rescored. Very late events are still stored
but counted separately so they never silently change old results.

On a first load there is no watermark, so nothing is late.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from riskdetect.schema import Event

DEFAULT_VERY_LATE_AFTER = timedelta(days=7)


@dataclass
class Lateness:
    late: int = 0
    very_late: int = 0
    actors_to_rescore: set[str] = field(default_factory=set)


def check_lateness(
    events: list[Event],
    watermark: datetime | None,
    very_late_after: timedelta = DEFAULT_VERY_LATE_AFTER,
) -> Lateness:
    result = Lateness()
    if watermark is None:
        return result
    for event in events:
        if event.occurred_at < watermark:
            result.late += 1
            result.actors_to_rescore.add(event.actor_id)
            if event.occurred_at < watermark - very_late_after:
                result.very_late += 1
    return result
