"""Evidence from sources other than rules, such as anomaly models.

A source looks at one feature row and returns signals. Each signal is combined
with rule hits in exactly the same way (each removes a share of the remaining
doubt), and each carries a reason a person can read.

- ``strong`` signals can, like rules with a score floor, take a user to REVIEW.
- Weak signals alone stay below REVIEW: "unusual" is not the same as "bad".
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Signal:
    code: str  # stable identifier, e.g. "M001_population_anomaly"
    source: str  # e.g. "model:population_anomaly"
    category: str
    strength: float  # 0-1
    strong: bool
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)

    # The same shape as a rule hit, so both combine identically.
    active: bool = True
    critical: bool = False


class Evidence(Protocol):
    """Anything that can raise a score: a rule hit or a model signal."""

    @property
    def active(self) -> bool: ...
    @property
    def code(self) -> str: ...
    @property
    def category(self) -> str: ...
    @property
    def strength(self) -> float: ...
    @property
    def strong(self) -> bool: ...
    @property
    def critical(self) -> bool: ...


class SignalSource(Protocol):
    name: str

    def signals(self, row: Mapping[str, Any]) -> list[Signal]: ...
