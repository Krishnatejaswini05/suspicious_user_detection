"""Keeps one running summary per actor and computes features from them.

Events must be applied in time order for timing features to be exact; late
events are still counted in every window.
"""

from collections.abc import Iterable
from datetime import datetime

from riskdetect.features.definition import Feature, FeatureValue
from riskdetect.features.registry import all_features
from riskdetect.features.state import ActorState
from riskdetect.schema import Event


class FeatureEngine:
    def __init__(self, platform: str, features: Iterable[Feature] | None = None) -> None:
        self.platform = platform
        self.features = tuple(features) if features is not None else all_features()
        self.states: dict[str, ActorState] = {}

    def state(self, actor_id: str) -> ActorState:
        state = self.states.get(actor_id)
        if state is None:
            state = self.states[actor_id] = ActorState(actor_id)
        return state

    def apply(self, event: Event) -> None:
        if event.platform != self.platform:
            raise ValueError(f"engine for {self.platform!r} got an event from {event.platform!r}")
        self.state(event.actor_id).apply(event)
        owner = event.target.owner_actor_id if event.target else None
        if owner is not None and owner != event.actor_id:
            self.state(owner).apply_received(event)

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
