"""Coordination features: questions about what other accounts on the platform did."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from conftest import EventFactory
from riskdetect.features import FeatureEngine
from riskdetect.features.crowd import CrowdState

T0 = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LONG = "Everyone please read this long message about the moderators before it is deleted"


@pytest.fixture
def engine(make_event: EventFactory) -> FeatureEngine:
    engine = FeatureEngine("synthetic_forum")
    # The platform has been watched for a month before T0 (coordination needs history).
    engine.apply(make_event(actor_id="watcher", occurred_at=T0 - timedelta(days=30)))
    return engine


def link(make_event: EventFactory, actor: str, at: datetime, site: str, **extra: Any) -> Any:
    return make_event(
        actor_id=actor, occurred_at=at, content={"kind": "post", "url_domains": [site]}, **extra
    )


def text(make_event: EventFactory, actor: str, at: datetime, text_hash: str, **extra: Any) -> Any:
    return make_event(
        actor_id=actor,
        occurred_at=at,
        content={"kind": "post", "text_hash": text_hash, "length": len(LONG)},
        **extra,
    )


class TestSitePush:
    def test_a_ring_site_has_only_new_linkers(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for i in range(6):
            for k in range(3):
                at = T0 - timedelta(days=2, hours=i, minutes=k)
                engine.apply(link(make_event, f"ring{i}", at, "ring-site.vip"))
        values = engine.compute("ring0", T0)
        assert values["top_site_new_linkers_7d"] == 6.0
        assert values["top_site_new_linker_share_7d"] == 1.0
        assert values["top_site_linkers"] == 6.0
        assert values["top_site_links_per_new_linker_7d"] == 3.0  # 18 links by 6 accounts

    def test_a_long_known_site_is_not_a_new_push(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for i in range(20):  # linked by many people for weeks
            engine.apply(link(make_event, f"old{i}", T0 - timedelta(days=20 + i), "github.com"))
        for k in range(3):
            engine.apply(link(make_event, "u1", T0 - timedelta(hours=k + 1), "github.com"))
        values = engine.compute("u1", T0)
        assert values["top_site_new_linker_share_7d"] == pytest.approx(1 / 21)
        assert values["top_site_linkers"] == 21.0

    def test_the_future_is_never_counted(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        engine.apply(link(make_event, "u1", T0 - timedelta(hours=1), "x.top"))
        engine.apply(link(make_event, "u2", T0 + timedelta(hours=1), "x.top"))
        assert engine.compute("u1", T0)["top_site_linkers"] == 1.0

    def test_unknown_without_links(self, engine: FeatureEngine, make_event: EventFactory) -> None:
        engine.apply(make_event(occurred_at=T0 - timedelta(hours=1)))
        assert engine.compute("u1", T0)["top_site_linkers"] is None


class TestCopiedAcrossAccounts:
    def test_counts_other_accounts_with_the_same_long_message(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for i in range(5):
            at = T0 - timedelta(hours=i + 1)
            engine.apply(text(make_event, f"u{i + 1}", at, "c" * 64))
        assert engine.compute("u1", T0)["copied_by_others_24h"] == 4.0

    def test_short_messages_are_ignored(self, make_event: EventFactory) -> None:
        crowd = CrowdState(first_active=lambda _: None)
        for i in range(5):
            event = make_event(
                actor_id=f"u{i}",
                occurred_at=T0 - timedelta(minutes=i + 1),
                content={"kind": "reply", "text_hash": "d" * 64, "length": 8},  # "thanks!"
            )
            crowd.apply(event)
        assert crowd.copied_by_others("u0", T0, timedelta(days=1)) == 0

    def test_copies_from_more_than_a_day_ago_are_forgotten(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for i in range(5):
            at = T0 - timedelta(days=3, hours=i)
            engine.apply(text(make_event, f"u{i + 1}", at, "e" * 64))
        engine.apply(make_event(occurred_at=T0 - timedelta(minutes=1)))  # time moves on
        assert engine.compute("u1", T0)["copied_by_others_24h"] == 0.0


class TestNewcomersAndInvites:
    def test_brand_new_accounts_flooding_a_space(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for i in range(10):
            at = T0 - timedelta(minutes=30 - i)
            engine.apply(make_event(actor_id=f"new{i}", occurred_at=at, space_id="s/games"))
        engine.apply(
            make_event(actor_id="veteran", occurred_at=T0 - timedelta(days=90), space_id="s/x")
        )
        engine.apply(
            make_event(
                actor_id="veteran", occurred_at=T0 - timedelta(minutes=5), space_id="s/games"
            )
        )
        assert engine.compute("new0", T0)["space_newcomers_1h"] == 10.0

    def test_invite_link_share(self, engine: FeatureEngine, make_event: EventFactory) -> None:
        for minute, site in enumerate(["discord.gg", "discord.gg", "t.me", "github.com"]):
            engine.apply(link(make_event, "u1", T0 - timedelta(minutes=minute + 1), site))
        assert engine.compute("u1", T0)["invite_link_share_7d"] == pytest.approx(3 / 4)


def test_nothing_is_judged_before_the_platform_has_been_watched(make_event: EventFactory) -> None:
    fresh = FeatureEngine("synthetic_forum")  # data starts today: every site looks new
    for i in range(6):
        fresh.apply(link(make_event, f"u{i}", T0 - timedelta(hours=i + 1), "youtube.com"))
        fresh.apply(make_event(actor_id=f"u{i}", occurred_at=T0 - timedelta(minutes=i + 1)))
    values = fresh.compute("u0", T0)
    assert values["top_site_new_linkers_7d"] is None
    assert values["top_site_linkers"] is None
    assert values["space_newcomers_1h"] is None
