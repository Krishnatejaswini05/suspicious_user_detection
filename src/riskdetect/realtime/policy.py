"""When to rescore a user.

Rescoring on every single event of a very active (but normal) user would waste
effort, so ordinary activity is batched: rescore after N new events, or once M
minutes have passed since the first unscored one. Alarming events (a link to a
known scam site) and late arrivals that change the past are rescored at once.
"""

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class RescorePolicy:
    every_events: int = 10
    every: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if self.every_events < 1:
            raise ValueError("every_events must be at least 1")
        if self.every <= timedelta(0):
            raise ValueError("every must be positive")
