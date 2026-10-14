"""Batch snapshots, including the key invariant: no information from the future."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conftest import EventFactory
from riskdetect.features import compute_snapshots, daily_snapshots, feature_names
from riskdetect.storage import ParquetEventStore

T0 = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
PLATFORM = "synthetic_forum"


@pytest.fixture
def store(tmp_path: Path, make_event: EventFactory) -> ParquetEventStore:
    store = ParquetEventStore(tmp_path / "events")
    events = []
    for hour in range(1, 48, 3):
        events.append(
            make_event(
                actor_id="u1",
                occurred_at=T0 - timedelta(hours=hour),
                content={"kind": "post", "text_hash": "a" * 64, "url_domains": ["bit.ly"]},
            )
        )
        events.append(make_event(actor_id="u2", occurred_at=T0 - timedelta(hours=hour, minutes=30)))
    store.append(events)
    return store


class TestNoLeakage:
    def test_future_events_do_not_change_past_features(
        self, store: ParquetEventStore, make_event: EventFactory
    ) -> None:
        before = compute_snapshots(store, PLATFORM, [T0])
        store.append(
            [
                make_event(
                    actor_id="u1", occurred_at=T0 + timedelta(minutes=m), content={"kind": "post"}
                )
                for m in range(0, 120, 5)
            ]
        )
        store.append([make_event(actor_id="u3", occurred_at=T0 + timedelta(hours=1))])
        assert compute_snapshots(store, PLATFORM, [T0]) == before

    def test_an_event_exactly_at_the_snapshot_is_excluded(
        self, store: ParquetEventStore, make_event: EventFactory
    ) -> None:
        before = compute_snapshots(store, PLATFORM, [T0])
        store.append([make_event(actor_id="u1", occurred_at=T0, content={"kind": "post"})])
        assert compute_snapshots(store, PLATFORM, [T0]) == before

    def test_one_pass_equals_separate_passes(self, store: ParquetEventStore) -> None:
        times = [T0 - timedelta(hours=12), T0]
        together = compute_snapshots(store, PLATFORM, times)
        separately = [row for t in times for row in compute_snapshots(store, PLATFORM, [t])]
        assert together == separately


def test_rows_have_every_feature_column(store: ParquetEventStore) -> None:
    rows = compute_snapshots(store, PLATFORM, [T0])
    assert {r["actor_id"] for r in rows} == {"u1", "u2"}
    for row in rows:
        assert list(row)[:3] == ["platform", "actor_id", "as_of"]
        assert set(row) == {"platform", "actor_id", "as_of", *feature_names()}


def test_unsupported_features_are_missing_not_zero(store: ParquetEventStore) -> None:
    [row, *_] = compute_snapshots(store, PLATFORM, [T0], available_fields={"content"})
    assert row["link_ratio_7d"] is None  # no "urls" on this pretend platform
    assert row["posts_24h"] is not None


def test_only_recently_active_actors(store: ParquetEventStore) -> None:
    later = T0 + timedelta(days=30)
    assert compute_snapshots(store, PLATFORM, [later]) == []
    assert len(compute_snapshots(store, PLATFORM, [later], active_within=None)) == 2


def test_daily_snapshots() -> None:
    times = daily_snapshots(T0 + timedelta(hours=5), T0 + timedelta(days=2, hours=1))
    assert times == [T0 + timedelta(days=d) for d in (1, 2, 3)]
