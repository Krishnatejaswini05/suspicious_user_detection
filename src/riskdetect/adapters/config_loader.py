"""Platform configuration: the YAML file that tells the generic adapter how to read
one platform's data.

A platform file describes *data* only (which column is the user, which action
means what). Detection logic never goes here. Every value is validated against
the canonical enums when the file is loaded, so a typo such as ``CONTENT_CREATD``
fails immediately instead of silently producing wrong events.
"""

from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from riskdetect.schema import (
    SUPPORTED_SCHEMA_VERSIONS,
    ContentKind,
    EventType,
    InteractionKind,
    ModerationActionType,
    ModerationSource,
    TargetType,
    Visibility,
)

SourceFormat = Literal["csv", "jsonl", "parquet"]

# Settings a platform file may override. Kept deliberately small: percentile-based
# features already adapt to each platform, so overrides are rare exceptions.
ALLOWED_OVERRIDE_SECTIONS = frozenset({"rules"})

_KIND_FIELD: dict[EventType, str] = {
    EventType.CONTENT_CREATED: "content_kind",
    EventType.CONTENT_EDITED: "content_kind",
    EventType.INTERACTION: "interaction_kind",
    EventType.MODERATION_ACTION: "moderation_action",
}
_DEFAULT_TARGET: dict[EventType, TargetType] = {
    EventType.CONTENT_EDITED: TargetType.CONTENT,
    EventType.CONTENT_DELETED: TargetType.CONTENT,
    EventType.INTERACTION: TargetType.CONTENT,
    EventType.REPORT_FILED: TargetType.CONTENT,
}


class PlatformConfigError(ValueError):
    """A platform configuration file is missing, unreadable or invalid."""


class _ConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EventMapping(_ConfigModel):
    """How one raw action value becomes a canonical event.

    YAML accepts a shorthand string, ``"CONTENT_CREATED/listing"`` or
    ``"INTERACTION/vote_up"`` or ``"REPORT_FILED"``, or the full mapping form
    when more detail is needed (target type, visibility, moderation source).
    """

    event_type: EventType
    content_kind: ContentKind | None = None
    interaction_kind: InteractionKind | None = None
    moderation_action: ModerationActionType | None = None
    moderation_source: ModerationSource = ModerationSource.HUMAN
    target_type: TargetType | None = None
    visibility: Visibility = Visibility.PUBLIC

    @model_validator(mode="before")
    @classmethod
    def _expand_shorthand(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        event_type, _, kind = value.partition("/")
        expanded: dict[str, str] = {"event_type": event_type.strip()}
        if kind:
            try:
                field = _KIND_FIELD[EventType(event_type.strip())]
            except (ValueError, KeyError):
                # Unknown type, or a type without kinds: let field validation report it.
                field = "content_kind"
            expanded[field] = kind.strip()
        return expanded

    @model_validator(mode="after")
    def _check_kinds(self) -> "EventMapping":
        needed = _KIND_FIELD.get(self.event_type)
        for field in ("content_kind", "interaction_kind", "moderation_action"):
            if field == needed and getattr(self, field) is None:
                raise ValueError(
                    f"{self.event_type} needs a {field} (e.g. '{self.event_type}/...')"
                )
            if field != needed and getattr(self, field) is not None:
                raise ValueError(f"{field} does not apply to {self.event_type}")
        return self

    @property
    def resolved_target_type(self) -> TargetType | None:
        """The configured target type, or a sensible default for the event type."""
        if self.target_type is not None:
            return self.target_type
        if self.interaction_kind is InteractionKind.FOLLOW:
            return TargetType.ACTOR
        return _DEFAULT_TARGET.get(self.event_type)


class EventTypeMap(_ConfigModel):
    from_field: str = Field(min_length=1)
    values: dict[str, EventMapping] = Field(min_length=1)


class FieldMap(_ConfigModel):
    """Which raw column holds each canonical field. Only two are required."""

    actor_id: str = Field(min_length=1)
    occurred_at: str = Field(min_length=1)
    event_id: str | None = None
    space_id: str | None = None
    text: str | None = None
    urls: str | None = None
    language: str | None = None
    target_id: str | None = None
    target_owner_id: str | None = None
    # Raw columns copied into Event.attributes. Empty by default (privacy by default):
    # only columns listed here are kept, so free-text columns cannot leak in.
    attributes: tuple[str, ...] = ()


class SourceConfig(_ConfigModel):
    format: SourceFormat
    path: str = Field(min_length=1)
    timezone: str = "UTC"  # used for timestamps that carry no timezone

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value


class PrivacyConfig(_ConfigModel):
    pseudonymize_ids: bool = False
    salt_env: str = "RISKDETECT_ID_SALT"


class PlatformConfig(_ConfigModel):
    platform: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    schema_version: int = 1
    source: SourceConfig
    fields: FieldMap
    event_types: EventTypeMap
    privacy: PrivacyConfig = PrivacyConfig()
    overrides: dict[str, dict[str, int | float | str | bool]] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, value: int) -> int:
        if value not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"schema_version {value} is not supported")
        return value

    @field_validator("overrides")
    @classmethod
    def _check_overrides(cls, value: dict[str, Any]) -> dict[str, Any]:
        unknown = set(value) - ALLOWED_OVERRIDE_SECTIONS
        if unknown:
            raise ValueError(f"overrides not allowed for: {sorted(unknown)}")
        return value

    def referenced_columns(self) -> dict[str, str]:
        """Canonical name -> raw column, for every column this config reads."""
        columns = {
            name: column
            for name, column in self.fields.model_dump(exclude={"attributes"}).items()
            if column is not None
        }
        columns["action"] = self.event_types.from_field
        for column in self.fields.attributes:
            columns[f"attributes.{column}"] = column
        return columns


def parse_platform_config(data: object, *, source: str = "<config>") -> PlatformConfig:
    """Validate an already-parsed YAML document."""
    try:
        return PlatformConfig.model_validate(data)
    except ValidationError as exc:
        problems = "\n".join(
            f"  {'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        )
        raise PlatformConfigError(f"Invalid platform config {source}:\n{problems}") from exc


def load_platform_config(path: Path) -> PlatformConfig:
    """Read and validate a platform YAML file. The file name must match ``platform``."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlatformConfigError(f"Platform config not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise PlatformConfigError(f"Platform config {path} is not valid YAML: {exc}") from exc

    config = parse_platform_config(data, source=str(path))
    if config.platform != path.stem:
        raise PlatformConfigError(
            f"Platform config {path}: 'platform: {config.platform}' must match the file name"
        )
    return config
