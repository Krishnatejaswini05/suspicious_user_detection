"""Counting things "in the last X" efficiently, without keeping a user's whole history.

Windows of up to a day (1h, 24h) are exact: the timestamps of the last day are
kept. Longer windows (7d, 30d) use per-day totals, so they count whole UTC
calendar days: "7d" means today plus the six days before it.
"""

from bisect import bisect_left, insort
from collections import Counter
from datetime import datetime, timedelta

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)
MONTH = timedelta(days=30)

# How long per-day totals are kept. Long enough for a 30-day baseline before today
# and for the 60-day dormancy check.
_DAILY_RETENTION_DAYS = 62


def day_index(moment: datetime) -> int:
    """The UTC calendar day of a moment, as a number (consecutive days differ by 1)."""
    return moment.date().toordinal()


class TimeSeriesCounter:
    """How many times something happened, queryable for any window ending at ``as_of``."""

    def __init__(self) -> None:
        self._recent: list[datetime] = []  # sorted; only the last day is kept
        self._daily: Counter[int] = Counter()

    def add(self, moment: datetime) -> None:
        insort(self._recent, moment)  # insort keeps order even for late, out-of-order events
        self._daily[day_index(moment)] += 1

    def count(self, window: timedelta, as_of: datetime) -> int:
        """Occurrences with ``as_of - window <= time < as_of`` (whole days for windows > 1 day)."""
        if window <= DAY:
            return bisect_left(self._recent, as_of) - bisect_left(self._recent, as_of - window)
        last = day_index(as_of)
        first = last - window.days + 1
        return sum(n for day, n in self._daily.items() if first <= day <= last)

    def daily_totals(self) -> dict[int, int]:
        return dict(self._daily)

    def prune(self, newest: datetime) -> None:
        """Forget what no window can reach any more."""
        cut = bisect_left(self._recent, newest - DAY)
        if cut:
            del self._recent[:cut]
        oldest_day = day_index(newest) - _DAILY_RETENTION_DAYS
        for day in [d for d in self._daily if d < oldest_day]:
            del self._daily[day]


class DailyTally:
    """Per-day counts of distinct things (domains, spaces, hours), unioned over a window."""

    def __init__(self) -> None:
        self._days: dict[int, Counter[str]] = {}

    def add(self, moment: datetime, item: str) -> None:
        self._days.setdefault(day_index(moment), Counter())[item] += 1

    def totals(self, window: timedelta, as_of: datetime) -> Counter[str]:
        last = day_index(as_of)
        first = last - window.days + 1
        total: Counter[str] = Counter()
        for day, counts in self._days.items():
            if first <= day <= last:
                total.update(counts)
        return total

    def prune(self, newest: datetime) -> None:
        oldest_day = day_index(newest) - _DAILY_RETENTION_DAYS
        for day in [d for d in self._days if d < oldest_day]:
            del self._days[day]
