from datetime import UTC, datetime
from typing import Any

import pytest

from riskdetect.schema import Event
from riskdetect.storage import EVENT_SCHEMA, event_to_row, row_to_event
from riskdetect.storage.serialization import events_to_table

T0 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)

EVENTS: list[dict[str, Any]] = [
    {
        "event_type": "CONTENT_CREATED",
        "content": {
            "kind": "reply",
            "visibility": "private",
            "text_hash": "a" * 64,
            "simhash": 2**64 - 1,  # largest 64-bit value must survive storage
            "length": 38,
            "language": "en",
            "url_domains": ["bit.ly", "example.com"],
            "mention_count": 2,
        },
        "target": {"type": "content", "id": "t1", "owner_actor_id": "u2"},
        "space_id": "f/tech",
        "attributes": {"price": "999", "flag": True},
    },
    {
        "event_type": "INTERACTION",
        "interaction": {"kind": "vote_up", "value": 1.5},
        "target": {"type": "content", "id": "t1"},
    },
    {
        "event_type": "MODERATION_ACTION",
        "moderation": {"action": "ban", "source": "human", "reason_category": "spam"},
    },
    {"event_type": "ACCOUNT_CREATED"},
]


@pytest.mark.parametrize("extra", EVENTS, ids=[e["event_type"] for e in EVENTS])
def test_round_trip(extra: dict[str, object]) -> None:
    event = Event.model_validate(
        {
            "event_id": "synthetic_forum:x",
            "platform": "synthetic_forum",
            "actor_id": "u1",
            "occurred_at": T0,
            "ingested_at": T0,
            **extra,
        }
    )
    assert row_to_event(event_to_row(event)) == event


def test_table_matches_schema() -> None:
    event = Event.model_validate(
        {
            "event_id": "synthetic_forum:x",
            "platform": "synthetic_forum",
            "actor_id": "u1",
            "occurred_at": T0,
            "event_type": "ACCOUNT_CREATED",
        }
    )
    table = events_to_table([event])
    assert table.schema == EVENT_SCHEMA
    assert table.num_rows == 1
