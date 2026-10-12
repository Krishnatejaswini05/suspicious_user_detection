"""Entities other than events: Actor, Space and Label.

Labels are kept apart from events on purpose. The detector reads events and
features only; labels are read by training and evaluation. Keeping them in a
separate type (and later a separate store) makes leakage hard to introduce.
"""

from datetime import datetime

from pydantic import AwareDatetime, Field, field_validator, model_validator

from riskdetect.schema.enums import LabelCategory, LabelSource, SpaceKind
from riskdetect.schema.events import (
    AttributeValue,
    NonEmptyStr,
    PlatformName,
    StrictModel,
    to_utc,
)


class Actor(StrictModel):
    """An account on a platform. Account age is one feature among many, never a verdict."""

    actor_id: NonEmptyStr
    platform: PlatformName
    created_at: AwareDatetime | None = None
    is_verified: bool = False
    is_allowlisted: bool = False
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else to_utc(value)


class Space(StrictModel):
    """A place where activity happens: a community, channel, category or conversation."""

    space_id: NonEmptyStr
    platform: PlatformName
    kind: SpaceKind = SpaceKind.OTHER
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)


class Label(StrictModel):
    """Ground truth about an actor.

    ``abuse_start`` is when the bad behavior began (used to measure time-to-detect).
    ``decided_at`` is when someone found out (used to prevent leakage: a label may only
    be used for snapshots taken before the outcome window closes).
    """

    actor_id: NonEmptyStr
    platform: PlatformName
    category: LabelCategory
    decided_at: AwareDatetime
    source: LabelSource
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    abuse_start: AwareDatetime | None = None

    @field_validator("decided_at", "abuse_start")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else to_utc(value)

    @model_validator(mode="after")
    def _check_times(self) -> "Label":
        if self.category is LabelCategory.CLEAN and self.abuse_start is not None:
            raise ValueError("a clean label cannot have abuse_start")
        if self.abuse_start is not None and self.abuse_start > self.decided_at:
            raise ValueError("abuse_start cannot be after decided_at")
        return self
