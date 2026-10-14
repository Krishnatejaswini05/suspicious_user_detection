from datetime import UTC, datetime, timedelta

from riskdetect.features.windows import DAY, HOUR, WEEK, DailyTally, TimeSeriesCounter

T0 = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def test_short_windows_are_exact_and_exclude_as_of() -> None:
    counter = TimeSeriesCounter()
    for minutes in (-90, -59, -1, 0, 5):
        counter.add(T0 + timedelta(minutes=minutes))
    assert counter.count(HOUR, T0) == 2  # -59 and -1; T0 itself is not "before T0"
    assert counter.count(DAY, T0) == 3
    assert counter.count(HOUR, T0 + timedelta(minutes=10)) == 3  # -1, 0 and 5 (not -59)


def test_long_windows_count_whole_days() -> None:
    counter = TimeSeriesCounter()
    for days in (0, 1, 6, 7, 20):
        counter.add(T0 - timedelta(days=days))
    assert counter.count(WEEK, T0 + timedelta(minutes=1)) == 3  # today and the 6 days before


def test_late_events_are_inserted_in_order() -> None:
    counter = TimeSeriesCounter()
    counter.add(T0)
    counter.add(T0 - timedelta(minutes=30))  # arrives late
    assert counter.count(HOUR, T0 - timedelta(minutes=10)) == 1


def test_prune_forgets_only_unreachable_data() -> None:
    counter = TimeSeriesCounter()
    counter.add(T0 - timedelta(days=100))
    counter.add(T0 - timedelta(hours=30))
    counter.add(T0 - timedelta(minutes=5))
    counter.prune(T0)
    assert counter.count(DAY, T0) == 1
    assert sum(counter.daily_totals().values()) == 2  # the 100-day-old one is gone


def test_daily_tally() -> None:
    tally = DailyTally()
    tally.add(T0, "bit.ly")
    tally.add(T0 - timedelta(days=1), "bit.ly")
    tally.add(T0 - timedelta(days=10), "old.com")
    assert tally.totals(WEEK, T0) == {"bit.ly": 2}
