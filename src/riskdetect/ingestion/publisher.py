"""Tell the rest of the system that new events were stored.

v1 hands events over in-process (a function call). Later this can become a real
message queue; only this module changes, because the pipeline only knows the
``Publisher`` interface.
"""

from collections.abc import Callable
from typing import Protocol

from riskdetect.schema import Event


class Publisher(Protocol):
    def publish(self, events: list[Event]) -> None: ...


class NullPublisher:
    """Publishes nowhere. Used when nothing is listening yet (e.g. a bulk historical load)."""

    def publish(self, events: list[Event]) -> None:
        return None


class CallbackPublisher:
    """Calls each subscriber with every batch of new events (realtime/ subscribes here later)."""

    def __init__(self, *subscribers: Callable[[list[Event]], None]) -> None:
        self.subscribers = list(subscribers)

    def publish(self, events: list[Event]) -> None:
        for subscriber in self.subscribers:
            subscriber(events)
