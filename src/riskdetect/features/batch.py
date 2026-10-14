"""Features for many actors at many past moments ("snapshots"), for training and evaluation.

Stored events are replayed once, in time order, through the same running
summaries the realtime watcher will use. Just before the first event at or after
a snapshot time is applied, every active actor's features are recorded. So a
snapshot "as of t" can only ever reflect events that happened strictly before t.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from riskdetect.features.availability import supported_features
from riskdetect.features.engine import FeatureEngine
from riskdetect.features.registry import feature_names
from riskdetect.features.windows import WEEK
from riskdetect.storage import EventStore

FeatureRow = dict[str, Any]  # platform, actor_id, as_of, then one column per feature


def daily_snapshots(first: datetime, last: datetime) -> list[datetime]:
    """Every UTC midnight after ``first`` up to and including the midnight after ``last``."""
    day = first.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    end = last.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    times = []
    while day <= end:
        times.append(day)
        day += timedelta(days=1)
    return times


def compute_snapshots(
    store: EventStore,
    platform: str,
    snapshot_times: Iterable[datetime],
    *,
    available_fields: Iterable[str] | None = None,
    active_within: timedelta | None = WEEK,
) -> list[FeatureRow]:
    """One row per (snapshot, actor active within ``active_within`` before it).

    Every row has a column for every registered feature, so tables line up across
    platforms; features the platform's data cannot support are None.
    """
    times = sorted(set(snapshot_times))
    if not times:
        return []
    engine = FeatureEngine(platform, supported_features(available_fields))
    names = feature_names()
    rows: list[FeatureRow] = []
    pending = 0
    for event in store.iter_events(platform, end=times[-1]):
        while pending < len(times) and event.occurred_at >= times[pending]:
            rows.extend(_snapshot(engine, times[pending], active_within, names))
            pending += 1
        engine.apply(event)
    for as_of in times[pending:]:
        rows.extend(_snapshot(engine, as_of, active_within, names))
    return rows


def _snapshot(
    engine: FeatureEngine, as_of: datetime, active_within: timedelta | None, names: list[str]
) -> list[FeatureRow]:
    since = as_of - active_within if active_within is not None else None
    rows = []
    for actor in engine.active_actors(as_of, since):
        values = engine.compute(actor, as_of)
        row: FeatureRow = {"platform": engine.platform, "actor_id": actor, "as_of": as_of}
        row.update({name: values.get(name) for name in names})
        rows.append(row)
    return rows
