"""The live desk: update a user's running summary the moment they act, and rescore when needed.

It uses the very same FeatureEngine as the nightly batch, so live and batch
features agree (tested). Feed it events in time order, for example by
subscribing ``on_events`` to the ingestion pipeline's publisher.

Running summaries live in memory. After a restart they are rebuilt from the event
store with ``warm_up``: stored events are the source of truth.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta

from riskdetect.features import FeatureEngine, PercentileTable, supported_features
from riskdetect.realtime.policy import RescorePolicy
from riskdetect.schema import Event, EventType
from riskdetect.scoring import RiskResult, Scorer, Tier
from riskdetect.storage import EventStore

ResultCallback = Callable[[RiskResult], None]
EscalationCallback = Callable[[RiskResult, Tier | None], None]
ActorKey = tuple[str, str]  # (platform, actor_id)

_TIER_RANK = {Tier.LOW: 0, Tier.WATCH: 1, Tier.REVIEW: 2, Tier.HIGH: 3}
_JUST_AFTER = timedelta(microseconds=1)  # score "as of" just after the latest event


class RealtimeProcessor:
    def __init__(
        self,
        scorer: Scorer,
        *,
        percentiles: Mapping[str, PercentileTable] | None = None,
        available_fields: Mapping[str, Iterable[str]] | None = None,
        blocked_domains: frozenset[str] = frozenset(),
        policy: RescorePolicy | None = None,
        on_result: ResultCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> None:
        """
        ``percentiles`` and ``available_fields`` are per platform; platforms without
        percentiles simply have no ``*_pct`` values, so percentile rules cannot fire.
        ``on_escalation`` is called when a user moves up into REVIEW or HIGH.
        """
        self.scorer = scorer
        self.percentiles = dict(percentiles or {})
        self.available_fields = {p: set(f) for p, f in (available_fields or {}).items()}
        self.blocked_domains = blocked_domains
        self.policy = policy or RescorePolicy()
        self.on_result = on_result
        self.on_escalation = on_escalation
        self.engines: dict[str, FeatureEngine] = {}
        self.latest: dict[ActorKey, RiskResult] = {}
        self._now: dict[str, datetime] = {}  # newest event time seen per platform
        self._pending: dict[ActorKey, int] = {}  # events since the last score
        self._pending_since: dict[ActorKey, datetime] = {}

    # -- feeding ---------------------------------------------------------------

    def on_events(self, events: list[Event]) -> None:
        """Publisher callback: process a batch of newly stored events, in order."""
        for event in events:
            self.process(event)

    def process(self, event: Event) -> RiskResult | None:
        """Apply one event; rescore its actor if the policy says so. Returns the new score."""
        platform, actor = event.platform, event.actor_id
        engine = self._engine(platform)
        previous_seen = engine.state(actor).last_seen
        engine.apply(event)
        now = max(self._now.get(platform, event.occurred_at), event.occurred_at)
        self._now[platform] = now

        if event.event_type is EventType.ACCOUNT_CREATED:
            return None  # signing up is not behavior; nothing to judge yet

        key = (platform, actor)
        self._pending[key] = self._pending.get(key, 0) + 1
        self._pending_since.setdefault(key, event.occurred_at)

        late = previous_seen is not None and event.occurred_at < previous_seen
        due = (
            self._pending[key] >= self.policy.every_events
            or now - self._pending_since[key] >= self.policy.every
        )
        if late or due or self._is_alarming(event):
            return self._score(key, now)
        return None

    def observe(self, event: Event) -> None:
        """Apply an event to the running summaries without scoring (history warm-up)."""
        engine = self._engine(event.platform)
        engine.apply(event)
        now = self._now.get(event.platform, event.occurred_at)
        self._now[event.platform] = max(now, event.occurred_at)

    def latest_time(self, platform: str) -> datetime | None:
        """The newest event time seen for a platform ("now", from the data's point of view)."""
        return self._now.get(platform)

    def score_now(self, platform: str, actor_id: str) -> RiskResult | None:
        """Score one user from their current running summary (None if never seen)."""
        engine = self.engines.get(platform)
        if engine is None or actor_id not in engine.states or platform not in self._now:
            return None
        return self._score((platform, actor_id), self._now[platform])

    def flush(self) -> list[RiskResult]:
        """Score every user with unscored events (e.g. at the end of a replay)."""
        return [self._score(key, self._now[key[0]]) for key in sorted(self._pending)]

    def warm_up(self, store: EventStore, platform: str, *, until: datetime | None = None) -> int:
        """Rebuild running summaries from stored events, without scoring. Returns events read."""
        count = 0
        for event in store.iter_events(platform, end=until):
            self.observe(event)
            count += 1
        return count

    # -- internals -------------------------------------------------------------

    def _engine(self, platform: str) -> FeatureEngine:
        engine = self.engines.get(platform)
        if engine is None:
            fields = self.available_fields.get(platform)
            engine = FeatureEngine(platform, supported_features(fields), self.blocked_domains)
            self.engines[platform] = engine
        return engine

    def _is_alarming(self, event: Event) -> bool:
        content = event.content
        return bool(content and self.blocked_domains.intersection(content.url_domains))

    def _score(self, key: ActorKey, now: datetime) -> RiskResult:
        platform, actor = key
        as_of = now + _JUST_AFTER  # features include everything up to and including `now`
        row: dict[str, object] = {"platform": platform, "actor_id": actor, "as_of": as_of}
        row.update(self.engines[platform].compute(actor, as_of))
        table = self.percentiles.get(platform)
        if table is not None:
            row = table.add_columns([row])[0]
        result = self.scorer.score(row)

        self._pending.pop(key, None)
        self._pending_since.pop(key, None)
        previous = self.latest.get(key)
        self.latest[key] = result
        if self.on_result is not None:
            self.on_result(result)
        previous_tier = previous.tier if previous else None
        escalated = _TIER_RANK[result.tier] > _TIER_RANK[previous_tier or Tier.LOW]
        if escalated and result.tier in (Tier.REVIEW, Tier.HIGH) and self.on_escalation:
            self.on_escalation(result, previous_tier)
        return result
