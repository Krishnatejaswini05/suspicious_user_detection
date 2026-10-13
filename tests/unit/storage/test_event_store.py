from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conftest import EventFactory
from riskdetect.storage import ParquetEventStore

T0 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> ParquetEventStore:
    return ParquetEventStore(tmp_path / "events")


def test_empty_store(store: ParquetEventStore) -> None:
    assert store.count() == 0
    assert store.exists(["a", "b"]) == set()
    assert store.max_occurred_at("synthetic_forum") is None
    assert store.get_actor_events("synthetic_forum", "u1") == []
    assert list(store.iter_events()) == []


def test_append_partitions_by_platform_and_utc_date(
    store: ParquetEventStore, make_event: EventFactory
) -> None:
    store.append(
        [
            make_event(occurred_at=T0),
            make_event(occurred_at=T0 + timedelta(days=1)),
            make_event(
                platform="synthetic_chat",
                event_id="synthetic_chat:1",
                occurred_at=T0,
            ),
        ]
    )
    folders = sorted(p.relative_to(store.directory).as_posix() for p in store.directory.glob("*/*"))
    assert folders == [
        "platform=synthetic_chat/date=2026-08-01",
        "platform=synthetic_forum/date=2026-08-01",
        "platform=synthetic_forum/date=2026-08-02",
    ]
    assert store.count() == 3
    assert store.count("synthetic_forum") == 2


def test_round_trip_through_storage(store: ParquetEventStore, make_event: EventFactory) -> None:
    event = make_event(
        content={"kind": "post", "text_hash": "b" * 64, "simhash": 2**63, "url_domains": ["a.com"]}
    )
    store.append([event])
    [loaded] = store.get_actor_events("synthetic_forum", "u1")
    assert loaded == event
    assert loaded.occurred_at.tzinfo is not None


def test_exists(store: ParquetEventStore, make_event: EventFactory) -> None:
    first, second = make_event(), make_event()
    store.append([first])
    assert store.exists([first.event_id, second.event_id, first.event_id]) == {first.event_id}


def test_actor_events_until_is_exclusive_and_ordered(
    store: ParquetEventStore, make_event: EventFactory
) -> None:
    times = [T0 + timedelta(minutes=m) for m in (30, 0, 10, 20)]
    store.append([make_event(occurred_at=t) for t in times])
    store.append([make_event(actor_id="u2", occurred_at=T0)])

    until_20 = store.get_actor_events("synthetic_forum", "u1", until=T0 + timedelta(minutes=20))
    assert [e.occurred_at for e in until_20] == [T0, T0 + timedelta(minutes=10)]

    window = store.get_actor_events(
        "synthetic_forum", "u1", since=T0 + timedelta(minutes=10), until=T0 + timedelta(minutes=30)
    )
    assert [e.occurred_at for e in window] == [
        T0 + timedelta(minutes=10),
        T0 + timedelta(minutes=20),
    ]


def test_iter_events_filters_and_orders(store: ParquetEventStore, make_event: EventFactory) -> None:
    store.append([make_event(occurred_at=T0 + timedelta(days=d)) for d in (2, 0, 1)])
    store.append([make_event(platform="synthetic_chat", event_id="synthetic_chat:1")])
    forum = list(store.iter_events("synthetic_forum", start=T0 + timedelta(days=1)))
    assert [e.occurred_at.day for e in forum] == [2, 3]
    assert len(list(store.iter_events())) == 4


def test_max_occurred_at(store: ParquetEventStore, make_event: EventFactory) -> None:
    store.append([make_event(occurred_at=T0), make_event(occurred_at=T0 + timedelta(hours=5))])
    assert store.max_occurred_at("synthetic_forum") == T0 + timedelta(hours=5)
    assert store.max_occurred_at("synthetic_chat") is None


def test_delete_actor(store: ParquetEventStore, make_event: EventFactory) -> None:
    store.append([make_event(actor_id="u1"), make_event(actor_id="u2")])
    store.append([make_event(actor_id="u1", occurred_at=T0 + timedelta(days=3))])
    assert store.delete_actor("synthetic_forum", "u1") == 2
    assert store.get_actor_events("synthetic_forum", "u1") == []
    assert store.count() == 1
    assert store.delete_actor("synthetic_forum", "nobody") == 0
