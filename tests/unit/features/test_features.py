"""Each feature on small, hand-made histories where the right answer is obvious."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from conftest import EventFactory
from riskdetect.features import FeatureEngine

T0 = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
PLATFORM = "synthetic_forum"


@pytest.fixture
def engine() -> FeatureEngine:
    return FeatureEngine(PLATFORM)


def post(make_event: EventFactory, at: datetime, **content: Any) -> Any:
    return make_event(occurred_at=at, content={"kind": "post", **content})


def signup(make_event: EventFactory, at: datetime, actor: str = "u1") -> Any:
    return make_event(event_type="ACCOUNT_CREATED", occurred_at=at, content=None, actor_id=actor)


def features(engine: FeatureEngine, as_of: datetime, actor: str = "u1") -> dict[str, Any]:
    return engine.compute(actor, as_of)


class TestMissingIsNotZero:
    def test_unknown_actor_has_missing_ratios(self, engine: FeatureEngine) -> None:
        values = features(engine, T0)
        assert values["duplicate_ratio_7d"] is None
        assert values["link_ratio_7d"] is None
        assert values["timing_regularity"] is None
        assert values["rate_vs_baseline"] is None  # too new to have a "usual"
        assert values["account_age_days"] is None
        assert values["posts_24h"] == 0.0


class TestLifecycle:
    def test_account_age_and_first_post(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        engine.apply(signup(make_event, T0 - timedelta(days=2)))
        engine.apply(post(make_event, T0 - timedelta(days=2) + timedelta(hours=3)))
        values = features(engine, T0)
        assert values["account_age_days"] == pytest.approx(2.0)
        assert values["hours_to_first_post"] == pytest.approx(3.0)


class TestContent:
    def test_exact_and_near_duplicates(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        engine.apply(
            post(make_event, T0 - timedelta(minutes=30), text_hash="a" * 64, simhash=0b1111)
        )
        engine.apply(post(make_event, T0 - timedelta(minutes=20), text_hash="a" * 64))  # exact
        engine.apply(
            post(make_event, T0 - timedelta(minutes=10), text_hash="b" * 64, simhash=0b1110)
        )
        engine.apply(post(make_event, T0 - timedelta(minutes=5), text_hash="c" * 64, simhash=2**40))
        assert features(engine, T0)["duplicate_ratio_24h"] == pytest.approx(2 / 4)

    def test_links_shorteners_and_domains(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for minutes, domains in ((40, ["bit.ly"]), (30, ["bit.ly"]), (20, ["bit.ly"]), (10, [])):
            engine.apply(post(make_event, T0 - timedelta(minutes=minutes), url_domains=domains))
        values = features(engine, T0)
        assert values["link_ratio_7d"] == pytest.approx(3 / 4)
        assert values["shortener_ratio_7d"] == pytest.approx(3 / 4)
        assert values["distinct_domains_7d"] == 1.0
        assert values["top_domain_share_7d"] == 1.0

    def test_spaces(self, engine: FeatureEngine, make_event: EventFactory) -> None:
        for i, space in enumerate(["f/a", "f/b", "f/a"]):
            engine.apply(make_event(occurred_at=T0 - timedelta(hours=i + 1), space_id=space))
        assert features(engine, T0)["distinct_spaces_7d"] == 2.0


class TestTiming:
    def test_machine_like_gaps_are_regular(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for i in range(20):
            engine.apply(post(make_event, T0 - timedelta(seconds=12 * (20 - i))))
        assert features(engine, T0)["timing_regularity"] == pytest.approx(1.0)

    def test_human_gaps_are_irregular(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        moment = T0 - timedelta(hours=10)
        for gap in (40, 300, 95, 1200, 15, 600, 70, 3000, 200, 30):
            moment += timedelta(seconds=gap)
            engine.apply(post(make_event, moment))
        assert features(engine, T0)["timing_regularity"] < 0.5

    def test_active_hours(self, engine: FeatureEngine, make_event: EventFactory) -> None:
        for hours_ago in range(1, 25):
            engine.apply(post(make_event, T0 - timedelta(hours=hours_ago)))
        assert features(engine, T0)["active_hours_7d"] == 24.0


class TestChange:
    def test_spike_against_own_baseline(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for day in range(10, 0, -1):  # one post a day for 10 days
            engine.apply(post(make_event, T0 - timedelta(days=day)))
        assert features(engine, T0)["rate_vs_baseline"] == pytest.approx(1.0, abs=0.2)
        for minute in range(30):  # then a burst today
            engine.apply(post(make_event, T0 - timedelta(minutes=minute + 1)))
        assert features(engine, T0)["rate_vs_baseline"] > 10

    def test_dormancy(self, engine: FeatureEngine, make_event: EventFactory) -> None:
        engine.apply(post(make_event, T0 - timedelta(days=20)))
        engine.apply(post(make_event, T0 - timedelta(hours=1)))
        assert features(engine, T0)["dormancy_gap_days"] == 19.0


class TestResponseFromOthers:
    def test_reports_and_replies_count_for_the_target_owner(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        engine.apply(post(make_event, T0 - timedelta(hours=2)))
        target = {"type": "content", "id": "t1", "owner_actor_id": "u1"}
        engine.apply(
            make_event(
                actor_id="u2",
                occurred_at=T0 - timedelta(hours=1),
                content={"kind": "reply"},
                target=target,
            )
        )
        engine.apply(
            make_event(
                actor_id="u3",
                event_type="REPORT_FILED",
                occurred_at=T0 - timedelta(minutes=30),
                content=None,
                target=target,
            )
        )
        values = features(engine, T0)
        assert values["replies_per_post_7d"] is None  # one post: too few to judge
        assert values["reports_received_7d"] == 1.0
        assert features(engine, T0, actor="u2")["reports_received_7d"] == 0.0

        engine.apply(post(make_event, T0 - timedelta(hours=3)))
        engine.apply(post(make_event, T0 - timedelta(hours=4)))
        assert features(engine, T0)["replies_per_post_7d"] == pytest.approx(1 / 3)

    def test_wrong_platform_is_rejected(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        with pytest.raises(ValueError):
            engine.apply(make_event(platform="synthetic_chat", event_id="synthetic_chat:1"))


class TestChangeVersusOwnPast:
    def test_links_up_compared_with_own_past(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for day in range(12, 2, -1):  # a quiet past: one post a day, every second one linked
            domains = ["docs.org"] if day % 2 else []
            engine.apply(post(make_event, T0 - timedelta(days=day), url_domains=domains))
        for minute in range(6):  # today: every post linked
            engine.apply(
                post(make_event, T0 - timedelta(minutes=minute + 1), url_domains=["x.top"])
            )
        values = features(engine, T0)
        assert values["link_ratio_change_24h"] == pytest.approx(1.0 - 0.5)

    def test_an_expert_who_always_links_shows_no_change(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for day in range(12, 2, -1):
            engine.apply(post(make_event, T0 - timedelta(days=day), url_domains=["github.com"]))
        for minute in range(6):
            engine.apply(
                post(make_event, T0 - timedelta(minutes=minute + 1), url_domains=["github.com"])
            )
        assert features(engine, T0)["link_ratio_change_24h"] == 0.0

    def test_unknown_without_enough_past(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for minute in range(6):
            engine.apply(
                post(make_event, T0 - timedelta(minutes=minute + 1), url_domains=["x.top"])
            )
        assert features(engine, T0)["link_ratio_change_24h"] is None
        assert features(engine, T0)["new_domain_link_share_24h"] is None

    def test_links_to_sites_never_used_before(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for day in range(12, 2, -1):
            engine.apply(post(make_event, T0 - timedelta(days=day), url_domains=["github.com"]))
        domains = ["github.com", "x.top", "x.top", "x.top"]
        for minute, domain in enumerate(domains):
            engine.apply(post(make_event, T0 - timedelta(minutes=minute + 1), url_domains=[domain]))
        assert features(engine, T0)["new_domain_link_share_24h"] == pytest.approx(3 / 4)

    def test_no_past_links_makes_every_link_new(
        self, engine: FeatureEngine, make_event: EventFactory
    ) -> None:
        for day in range(12, 2, -1):
            engine.apply(post(make_event, T0 - timedelta(days=day)))
        engine.apply(post(make_event, T0 - timedelta(minutes=1), url_domains=["x.top"]))
        assert features(engine, T0)["new_domain_link_share_24h"] == 1.0
