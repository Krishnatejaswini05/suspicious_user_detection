"""What a feature is: a named, versioned formula over an actor's running summary.

``None`` means "cannot tell" (missing), which is different from 0. For example,
a user with no posts has no duplicate ratio, not a duplicate ratio of 0.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from riskdetect.features.state import ActorState

FeatureValue = float | None
Formula = Callable[[ActorState, datetime], FeatureValue]


@dataclass(frozen=True)
class Feature:
    name: str
    version: int
    family: str
    description: str
    compute: Formula
    # Data the platform must provide (names from the adapter mapping report, e.g. "text").
    requires: frozenset[str] = frozenset()
    # Raw counts are also expressed as a percentile within their platform, which is what
    # makes them comparable across platforms. Ratios and absolute measures are not.
    percentile: bool = False

    def __call__(self, state: ActorState, as_of: datetime) -> FeatureValue:
        return self.compute(state, as_of)
