"""Keeps one running summary per actor and computes features from them.

Events must be applied in time order for timing features to be exact; late
events are still counted in every window.
"""

from collections import deque
from collections.abc import Iterable
from datetime import datetime
from statistics import median

from riskdetect.features.crowd import CrowdState
from riskdetect.features.definition import Feature, FeatureValue
from riskdetect.features.registry import all_features
from riskdetect.features.state import ActorState
from riskdetect.schema import Event, EventType

# The usual price in a category is the median of other sellers' recent listings there.
_PRICE_REFERENCE_SIZE = 200
_MIN_PRICE_REFERENCE = 10  # fewer listings than this: the usual price is unknown


class FeatureEngine:
    def __init__(
        self,
        platform: str,
        features: Iterable[Feature] | None = None,
        blocked_domains: frozenset[str] = frozenset(),
    ) -> None:
        self.platform = platform
        self.features = tuple(features) if features is not None else all_features()
        self.blocked_domains = blocked_domains
        self.states: dict[str, ActorState] = {}
        # Recent asking prices per space (category), from listings applied so far: only
        # the past, so a listing is never compared with prices that came after it.
        self.space_prices: dict[str, deque[float]] = {}
        # What the whole platform has done so far, for coordination features.
        self.crowd = CrowdState(first_active=self._first_active)

    def state(self, actor_id: str) -> ActorState:
        state = self.states.get(actor_id)
        if state is None:
            state = self.states[actor_id] = ActorState(
                actor_id, self.blocked_domains, crowd=self.crowd
            )
        return state

    def apply(self, event: Event) -> None:
        if event.platform != self.platform:
            raise ValueError(f"engine for {self.platform!r} got an event from {event.platform!r}")
        self.state(event.actor_id).apply(event)
        self.crowd.apply(event)
        self._compare_price(event)
        owner = event.target.owner_actor_id if event.target else None
        if owner is not None and owner != event.actor_id:
            self.state(owner).apply_received(event)

    def _first_active(self, actor_id: str) -> datetime | None:
        state = self.states.get(actor_id)
        return state.first_active if state is not None else None

    def _compare_price(self, event: Event) -> None:
        content = event.content
        if (
            event.event_type is not EventType.CONTENT_CREATED
            or content is None
            or content.price is None
            or event.space_id is None
        ):
            return
        prices = self.space_prices.setdefault(event.space_id, deque(maxlen=_PRICE_REFERENCE_SIZE))
        if len(prices) >= _MIN_PRICE_REFERENCE:
            usual = median(prices)
            if usual > 0:
                self.state(event.actor_id).record_listing_price(
                    event.occurred_at, content.price / usual
                )
        prices.append(content.price)

    def compute(self, actor_id: str, as_of: datetime) -> dict[str, FeatureValue]:
        """All engine features for one actor as of ``as_of``.

        The caller must not have applied any event at or after ``as_of``.
        """
        state = self.state(actor_id)
        return {feature.name: feature(state, as_of) for feature in self.features}

    def active_actors(self, as_of: datetime, within: datetime | None) -> list[str]:
        """Actors with any activity since ``within`` (all known actors if None), sorted."""
        if within is None:
            return sorted(self.states)
        return sorted(
            actor
            for actor, state in self.states.items()
            if state.last_seen is not None and within <= state.last_seen < as_of
        )
