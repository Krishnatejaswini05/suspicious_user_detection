"""Never count the same event twice.

A duplicate is the *same event delivered again* (same event_id): a file loaded
twice, or a network resend. A user repeating an action creates new events with
new IDs; those are real behavior and are always kept.
"""

from riskdetect.schema import Event
from riskdetect.storage import EventStore


def split_new(events: list[Event], store: EventStore) -> tuple[list[Event], int]:
    """Return (events not seen before, number of duplicates dropped).

    Checks both within this batch and against what is already stored.
    """
    unique: dict[str, Event] = {}
    in_batch_duplicates = 0
    for event in events:
        if event.event_id in unique:
            in_batch_duplicates += 1
        else:
            unique[event.event_id] = event
    already_stored = store.exists(unique)
    new = [event for event_id, event in unique.items() if event_id not in already_stored]
    return new, in_batch_duplicates + len(already_stored)
