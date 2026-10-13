"""The one adapter that serves every platform, driven by its YAML config.

For each raw record it looks up the action in ``event_types``, reads the mapped
columns, turns text into fingerprints (then discards it), and builds an Event
through ``parse_event``. Records that cannot be translated become Rejections with
a reason, never silent drops.

Privacy: raw text never reaches an Event, and the text column is removed from the
copy of the record kept on a Rejection, so quarantine does not hold it either.
"""

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from riskdetect.adapters.base import AdapterResult
from riskdetect.adapters.config_loader import EventMapping, PlatformConfig, PlatformConfigError
from riskdetect.adapters.readers import RawRecord, read_records
from riskdetect.adapters.report import MappingReport
from riskdetect.adapters.transforms import (
    count_mentions,
    extract_domains,
    hash_text,
    parse_time,
    pseudonymize_id,
    simhash_text,
)
from riskdetect.schema import (
    Rejection,
    RejectionReason,
    TargetType,
    derived_event_id,
    parse_event,
    scoped_event_id,
)

_SCALAR_TYPES = (str, int, float, bool)


def _as_text(value: object) -> str | None:
    """A non-empty string, or None. Numbers become strings (IDs are often numeric)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_attribute(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, _SCALAR_TYPES):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class GenericAdapter:
    def __init__(
        self,
        config: PlatformConfig,
        *,
        base_dir: Path | None = None,
        id_salt: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """
        ``base_dir`` resolves a relative ``source.path`` (default: current directory).
        ``id_salt`` is required when the config enables ID pseudonymization; by default
        it is read from the environment variable named in ``privacy.salt_env``.
        ``now`` fixes the reference time for future-timestamp checks (used in tests).
        """
        self.config = config
        self.platform = config.platform
        self._base_dir = base_dir or Path.cwd()
        self._tz = ZoneInfo(config.source.timezone)
        self._now = now
        self._salt: str | None = None
        if config.privacy.pseudonymize_ids:
            self._salt = id_salt or os.environ.get(config.privacy.salt_env)
            if not self._salt:
                raise PlatformConfigError(
                    f"{self.platform}: pseudonymize_ids is on but no salt was given "
                    f"(set the {config.privacy.salt_env} environment variable)"
                )
        fields = config.fields
        self._private_columns = {c for c in (fields.text, fields.urls) if c}

    @property
    def source_path(self) -> Path:
        path = Path(self.config.source.path)
        return path if path.is_absolute() else self._base_dir / path

    def read(self) -> Iterator[RawRecord]:
        return read_records(self.source_path, self.config.source.format)

    def new_report(self) -> MappingReport:
        return MappingReport(self.platform, columns=self.config.referenced_columns())

    def to_events(self, record: RawRecord) -> list[AdapterResult]:
        return [self._translate(record)]

    # -- translation ---------------------------------------------------------

    def _translate(self, record: RawRecord) -> AdapterResult:
        if record.error is not None:
            return Rejection(RejectionReason.INVALID_STRUCTURE, record.error, (), {})

        data = record.data
        fields = self.config.fields
        action_field = self.config.event_types.from_field
        action = _as_text(data.get(action_field))
        mapping = self.config.event_types.values.get(action) if action is not None else None
        if mapping is None:
            return Rejection(
                RejectionReason.UNMAPPED_ACTION,
                f"{action_field}={action!r} is not listed in event_types for {self.platform}",
                (action_field,),
                self._redact(data),
            )

        try:
            occurred_at = parse_time(data.get(fields.occurred_at), self._tz)
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            return Rejection(
                RejectionReason.INVALID_TIMESTAMP,
                f"{fields.occurred_at}: {exc}",
                (fields.occurred_at,),
                self._redact(data),
            )

        actor_id = self._actor(data.get(fields.actor_id))
        content = self._content(data, mapping)
        target = self._target(data, mapping)
        event: dict[str, Any] = {
            "event_id": self._event_id(
                record, data, mapping, actor_id, occurred_at, target, content
            ),
            "platform": self.platform,
            "actor_id": actor_id,
            "event_type": mapping.event_type,
            "occurred_at": occurred_at,
            "space_id": _as_text(data.get(fields.space_id)) if fields.space_id else None,
            "target": target,
            "content": content,
            "interaction": (
                {"kind": mapping.interaction_kind} if mapping.interaction_kind else None
            ),
            "moderation": (
                {"action": mapping.moderation_action, "source": mapping.moderation_source}
                if mapping.moderation_action
                else None
            ),
            "attributes": {col: _as_attribute(data.get(col)) for col in fields.attributes},
        }

        result = parse_event(event, now=self._now)
        if isinstance(result, Rejection):
            # Keep the original record for repair, minus private text.
            return replace(result, raw=self._redact(data))
        return result

    def _actor(self, value: object) -> str | None:
        actor = _as_text(value)
        if actor is not None and self._salt is not None:
            return pseudonymize_id(actor, self._salt)
        return actor

    def _content(self, data: dict[str, Any], mapping: EventMapping) -> dict[str, Any] | None:
        if mapping.content_kind is None:
            return None
        fields = self.config.fields
        text = _as_text(data.get(fields.text)) if fields.text else None
        language = _as_text(data.get(fields.language)) if fields.language else None
        return {
            "kind": mapping.content_kind,
            "visibility": mapping.visibility,
            "text_hash": hash_text(text) if text else None,
            "simhash": simhash_text(text) if text else None,
            "length": len(text) if text else None,
            "language": language,
            "url_domains": extract_domains(data.get(fields.urls)) if fields.urls else (),
            "mention_count": count_mentions(text) if text else 0,
        }

    def _target(self, data: dict[str, Any], mapping: EventMapping) -> dict[str, Any] | None:
        fields = self.config.fields
        target_type = mapping.resolved_target_type
        target_id = _as_text(data.get(fields.target_id)) if fields.target_id else None
        if target_type is None or target_id is None:
            return None
        if target_type is TargetType.ACTOR:
            target_id = self._actor(target_id)
        owner = self._actor(data.get(fields.target_owner_id)) if fields.target_owner_id else None
        return {"type": target_type, "id": target_id, "owner_actor_id": owner}

    def _event_id(
        self,
        record: RawRecord,
        data: dict[str, Any],
        mapping: EventMapping,
        actor_id: str | None,
        occurred_at: datetime,
        target: dict[str, Any] | None,
        content: dict[str, Any] | None,
    ) -> str:
        native = (
            _as_text(data.get(self.config.fields.event_id)) if self.config.fields.event_id else None
        )
        if native is not None:
            return scoped_event_id(self.platform, native)
        return derived_event_id(
            platform=self.platform,
            actor_id=actor_id or "",
            event_type=mapping.event_type,
            occurred_at=occurred_at,
            source_position=record.position,
            target_id=target["id"] if target else None,
            text_hash=content["text_hash"] if content else None,
        )

    def _redact(self, data: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in data.items() if k not in self._private_columns}
