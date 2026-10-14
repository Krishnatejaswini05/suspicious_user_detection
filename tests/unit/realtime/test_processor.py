from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from conftest import EventFactory
from riskdetect.features import FeatureEngine
from riskdetect.realtime import RealtimeProcessor, RescorePolicy, replay
from riskdetect.rules import RuleSet
from riskdetect.rules.lists import load_domain_list
from riskdetect.scoring import RiskResult, Scorer, ScoringConfig, Tier
from riskdetect.storage import ParquetEventStore

T0 = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
CONFIG = ScoringConfig.model_validate(
    {
        "version": 1,
        "max_weight_score": 0.55,
        "confidence": {"medium_from": 10, "high_from": 40},
        "tiers": {"watch_from": 0.3, "review_from": 0.6, "high_from": 0.85},
        "actions": {"LOW": [], "WATCH": [], "REVIEW": ["review"], "HIGH": ["review"]},
        "allowlist_cap": 0.2,
    }
)
RULES = RuleSet.model_validate(
    {
        "version": 1,
        "rules": [
            {
                "id": "R001_burst",
                "description": "burst",
                "category": "spam",
                "score_floor": 0.7,
                "when": {"all": [{"feature": "posts_1h", "op": ">=", "value": 10}]},
                "reason": "{posts_1h:.0f} posts in an hour",
            },
            {
                "id": "R008_scam_site",
                "description": "scam site",
                "category": "scam",
                "score_floor": 0.9,
                "severity": "critical",
                "when": {"all": [{"feature": "blocked_domain_posts_7d", "op": ">=", "value": 1}]},
                "reason": "linked a scam site",
            },
        ],
    }
)


class Recorder:
    def __init__(self) -> None:
        self.results: list[RiskResult] = []
        self.escalations: list[tuple[str, Tier | None, Tier]] = []

    def result(self, result: RiskResult) -> None:
        self.results.append(result)

    def escalation(self, result: RiskResult, previous: Tier | None) -> None:
        self.escalations.append((result.actor_id, previous, result.tier))


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


def processor(recorder: Recorder, **kwargs: Any) -> RealtimeProcessor:
    return RealtimeProcessor(
        Scorer(RULES, CONFIG),
        blocked_domains=frozenset({"scam.site"}),
        on_result=recorder.result,
        on_escalation=recorder.escalation,
        **kwargs,
    )


def post(make_event: EventFactory, at: datetime, actor: str = "u1", **content: Any) -> Any:
    return make_event(actor_id=actor, occurred_at=at, content={"kind": "post", **content})


class TestWhenToRescore:
    def test_every_n_events(self, recorder: Recorder, make_event: EventFactory) -> None:
        live = processor(recorder, policy=RescorePolicy(every_events=3))
        results = [live.process(post(make_event, T0 + timedelta(seconds=i))) for i in range(7)]
        assert [r is not None for r in results] == [False, False, True, False, False, True, False]

    def test_after_enough_time(self, recorder: Recorder, make_event: EventFactory) -> None:
        live = processor(recorder, policy=RescorePolicy(every_events=100))
        assert live.process(post(make_event, T0)) is None
        assert live.process(post(make_event, T0 + timedelta(minutes=6))) is not None

    def test_signups_alone_are_not_scored(
        self, recorder: Recorder, make_event: EventFactory
    ) -> None:
        live = processor(recorder, policy=RescorePolicy(every_events=1))
        signup = make_event(event_type="ACCOUNT_CREATED", content=None, occurred_at=T0)
        assert live.process(signup) is None
        assert live.flush() == []

    def test_late_events_rescore_immediately(
        self, recorder: Recorder, make_event: EventFactory
    ) -> None:
        live = processor(recorder, policy=RescorePolicy(every_events=100))
        live.process(post(make_event, T0))
        assert live.process(post(make_event, T0 - timedelta(hours=1))) is not None

    def test_flush_scores_whatever_is_pending(
        self, recorder: Recorder, make_event: EventFactory
    ) -> None:
        live = processor(recorder, policy=RescorePolicy(every_events=100))
        live.process(post(make_event, T0, actor="u1"))
        live.process(post(make_event, T0, actor="u2"))
        assert [r.actor_id for r in live.flush()] == ["u1", "u2"]
        assert live.flush() == []

    def test_policy_validation(self) -> None:
        with pytest.raises(ValueError):
            RescorePolicy(every_events=0)
        with pytest.raises(ValueError):
            RescorePolicy(every=timedelta(0))


class TestScoring:
    def test_burst_escalates_once(self, recorder: Recorder, make_event: EventFactory) -> None:
        live = processor(recorder, policy=RescorePolicy(every_events=5))
        for i in range(20):
            live.process(post(make_event, T0 + timedelta(seconds=12 * i)))
        assert recorder.escalations == [("u1", Tier.LOW, Tier.REVIEW)]
        assert live.latest[("synthetic_forum", "u1")].tier is Tier.REVIEW

    def test_scam_link_is_scored_at_once_and_can_reach_high(
        self, recorder: Recorder, make_event: EventFactory
    ) -> None:
        live = processor(recorder, policy=RescorePolicy(every_events=100))
        result = live.process(post(make_event, T0, url_domains=["scam.site"]))
        assert result is not None
        assert result.tier is Tier.HIGH  # critical rule: direct evidence, even on day one
        assert result.reasons[0].text == "linked a scam site"

    def test_scores_include_the_triggering_event(
        self, recorder: Recorder, make_event: EventFactory
    ) -> None:
        live = processor(recorder, policy=RescorePolicy(every_events=1))
        result = live.process(post(make_event, T0))
        assert result is not None
        assert result.as_of > T0


def test_live_and_batch_features_agree(tmp_path: Path, make_event: EventFactory) -> None:
    store = ParquetEventStore(tmp_path / "events")
    events = [
        post(make_event, T0 - timedelta(minutes=7 * i), actor=f"u{i % 3}", url_domains=["a.com"])
        for i in range(30)
    ]
    store.append(events)
    live = RealtimeProcessor(Scorer(RULES, CONFIG))
    replay(store, "synthetic_forum", live, flush=False)
    batch = FeatureEngine("synthetic_forum")
    for event in store.iter_events("synthetic_forum"):
        batch.apply(event)
    as_of = T0 + timedelta(hours=1)
    for actor in ("u0", "u1", "u2"):
        assert live.engines["synthetic_forum"].compute(actor, as_of) == batch.compute(actor, as_of)


def test_warm_up_rebuilds_without_scoring(
    tmp_path: Path, make_event: EventFactory, recorder: Recorder
) -> None:
    store = ParquetEventStore(tmp_path / "events")
    store.append([post(make_event, T0 + timedelta(seconds=i)) for i in range(15)])
    live = processor(recorder)
    assert live.warm_up(store, "synthetic_forum") == 15
    assert recorder.results == []
    assert (
        live.engines["synthetic_forum"].compute("u1", T0 + timedelta(minutes=1))["posts_1h"] == 15
    )


def test_domain_list_file(tmp_path: Path) -> None:
    path = tmp_path / "blocked.txt"
    path.write_text("# comment\nWWW.Scam.Site\n\nother.xyz  # trailing note\n", encoding="utf-8")
    assert load_domain_list(path) == {"scam.site", "other.xyz"}
    assert load_domain_list(tmp_path / "missing.txt") == frozenset()
    path.write_text("not a domain\n", encoding="utf-8")
    with pytest.raises(ValueError, match=":1:"):
        load_domain_list(path)
