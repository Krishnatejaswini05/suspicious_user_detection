"""The canonical Event: one thing one actor did at one time.

Every platform's data is translated into this shape by an adapter. Nothing
downstream of the adapters knows which platform an event came from, apart from
the ``platform`` field used for per-platform normalization.

Conventions:
- All timestamps are timezone-aware and stored in UTC. Naive datetimes are rejected,
  because guessing their timezone silently corrupts time-window features.
- Raw text is never stored. ``text_hash`` / ``simhash`` are fingerprints computed by
  the adapter, which then discards the text.
- For MODERATION_ACTION, ``actor_id`` is the account being acted on (the subject),
  not the moderator.
- For REPORT_FILED, ``actor_id`` is the reporter and ``target`` is what was reported.
"""

import re
from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from riskdetect.schema.enums import (
    ContentKind,
    EventType,
    InteractionKind,
    ModerationActionType,
    ModerationSource,
    TargetType,
    Visibility,
)
from riskdetect.schema.version import SCHEMA_VERSION

NonEmptyStr = Annotated[str, Field(min_length=1)]
PlatformName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
AttributeValue = str | int | float | bool | None

_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
_HEX_HASH_RE = re.compile(r"^[0-9a-f]{16,128}$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$")
_SIMHASH_LIMIT = 2**64


def to_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC; naive datetimes are rejected."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def normalize_domain(value: str) -> str:
    """Reduce a URL or host to a bare lowercase domain.

    ``"https://www.Bit.ly/x?y=1"`` -> ``"bit.ly"``.
    """
    host = value.strip().lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    for separator in ("/", "?", "#"):
        host = host.split(separator, 1)[0]
    host = host.rsplit("@", 1)[-1]  # drop user:password@
    host = host.split(":", 1)[0]  # drop :port
    host = host.rstrip(".")
    host = host.removeprefix("www.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"invalid domain: {value!r}") from exc
    if not _DOMAIN_RE.match(host):
        raise ValueError(f"invalid domain: {value!r}")
    return host


class StrictModel(BaseModel):
    """Immutable models that reject unknown fields, so mapping mistakes surface early."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Target(StrictModel):
    """What an event is aimed at."""

    type: TargetType
    id: NonEmptyStr
    owner_actor_id: NonEmptyStr | None = None


class Content(StrictModel):
    """Privacy-preserving description of something an actor created."""

    kind: ContentKind
    visibility: Visibility = Visibility.PUBLIC
    text_hash: str | None = None
    simhash: int | None = Field(default=None, ge=0, lt=_SIMHASH_LIMIT)
    length: int | None = Field(default=None, ge=0)
    language: str | None = None
    url_domains: tuple[str, ...] = ()
    mention_count: int = Field(default=0, ge=0)

    @field_validator("text_hash")
    @classmethod
    def _check_text_hash(cls, value: str | None) -> str | None:
        # A strict hex format also guards against raw text being mapped here by mistake.
        if value is not None and not _HEX_HASH_RE.match(value):
            raise ValueError("text_hash must be a lowercase hex digest (16-128 chars)")
        return value

    @field_validator("language")
    @classmethod
    def _check_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        if not _LANGUAGE_RE.match(value):
            raise ValueError("language must be a code like 'en' or 'pt-br'")
        return value

    @field_validator("url_domains", mode="before")
    @classmethod
    def _normalize_domains(cls, value: object) -> object:
        if isinstance(value, str) or not hasattr(value, "__iter__"):
            return value  # let pydantic report the type error
        return tuple(dict.fromkeys(normalize_domain(str(item)) for item in value))


class Interaction(StrictModel):
    kind: InteractionKind
    value: float | None = None


class Moderation(StrictModel):
    action: ModerationActionType
    source: ModerationSource
    reason_category: NonEmptyStr | None = None


# Blocks each event type must carry, and the event types each block is allowed on.
_REQUIRED_BLOCKS: dict[EventType, tuple[str, ...]] = {
    EventType.CONTENT_CREATED: ("content",),
    EventType.CONTENT_EDITED: ("content", "target"),
    EventType.CONTENT_DELETED: ("target",),
    EventType.INTERACTION: ("interaction", "target"),
    EventType.REPORT_FILED: ("target",),
    EventType.MODERATION_ACTION: ("moderation",),
}
_ALLOWED_ON: dict[str, frozenset[EventType]] = {
    "content": frozenset({EventType.CONTENT_CREATED, EventType.CONTENT_EDITED}),
    "interaction": frozenset({EventType.INTERACTION}),
    "moderation": frozenset({EventType.MODERATION_ACTION}),
}
_CONTENT_TARGETED = frozenset({EventType.CONTENT_EDITED, EventType.CONTENT_DELETED})


class Event(StrictModel):
    """One thing one actor did at one time, in platform-neutral form."""

    event_id: NonEmptyStr
    schema_version: int = SCHEMA_VERSION
    platform: PlatformName
    actor_id: NonEmptyStr
    event_type: EventType
    occurred_at: AwareDatetime
    ingested_at: AwareDatetime | None = None
    space_id: NonEmptyStr | None = None
    target: Target | None = None
    content: Content | None = None
    interaction: Interaction | None = None
    moderation: Moderation | None = None
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)

    @field_validator("occurred_at", "ingested_at")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else to_utc(value)

    @model_validator(mode="after")
    def _check_blocks(self) -> "Event":
        for block in _REQUIRED_BLOCKS.get(self.event_type, ()):
            if getattr(self, block) is None:
                raise ValueError(f"{self.event_type} requires '{block}'")
        for block, allowed in _ALLOWED_ON.items():
            if getattr(self, block) is not None and self.event_type not in allowed:
                raise ValueError(f"'{block}' is not allowed on {self.event_type}")
        if (
            self.event_type in _CONTENT_TARGETED
            and self.target is not None
            and self.target.type is not TargetType.CONTENT
        ):
            raise ValueError(f"{self.event_type} must target content")
        return self
