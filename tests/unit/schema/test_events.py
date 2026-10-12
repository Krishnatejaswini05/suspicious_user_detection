from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from riskdetect.schema import (
    Content,
    ContentKind,
    Event,
    EventType,
    TargetType,
    normalize_domain,
)

T0 = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


def event_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "event_id": "synthetic_market:post_1",
        "platform": "synthetic_market",
        "actor_id": "S42",
        "event_type": "CONTENT_CREATED",
        "occurred_at": T0,
        "space_id": "electronics",
        "content": {"kind": "listing", "url_domains": ["https://www.Bit.ly/deal"]},
    }
    data.update(overrides)
    return data


class TestEventBasics:
    def test_valid_content_event(self) -> None:
        event = Event.model_validate(event_data())
        assert event.event_type is EventType.CONTENT_CREATED
        assert event.content is not None
        assert event.content.kind is ContentKind.LISTING
        assert event.schema_version == 1

    def test_timestamps_are_converted_to_utc(self) -> None:
        ist = timezone(timedelta(hours=5, minutes=30))
        event = Event.model_validate(
            event_data(occurred_at=datetime(2026, 10, 2, 15, 30, tzinfo=ist))
        )
        assert event.occurred_at == T0
        assert event.occurred_at.utcoffset() == timedelta(0)

    def test_iso_string_timestamps_are_accepted(self) -> None:
        event = Event.model_validate(event_data(occurred_at="2026-10-02T10:00:00Z"))
        assert event.occurred_at == T0

    def test_naive_timestamp_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Event.model_validate(event_data(occurred_at=datetime(2026, 10, 2, 10, 0)))

    @pytest.mark.parametrize("field", ["event_id", "actor_id", "platform", "occurred_at"])
    def test_required_fields(self, field: str) -> None:
        data = event_data()
        del data[field]
        with pytest.raises(ValidationError):
            Event.model_validate(data)

    def test_empty_actor_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Event.model_validate(event_data(actor_id=""))

    @pytest.mark.parametrize("platform", ["Reddit", "my-platform", "1abc", ""])
    def test_platform_name_format(self, platform: str) -> None:
        with pytest.raises(ValidationError):
            Event.model_validate(event_data(platform=platform))

    def test_unknown_fields_are_rejected(self) -> None:
        # Catches YAML mapping mistakes such as a misspelled field name.
        with pytest.raises(ValidationError):
            Event.model_validate(event_data(actor_idd="S42"))

    def test_unknown_event_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Event.model_validate(event_data(event_type="CONTENT_CREATD"))

    def test_events_are_immutable(self) -> None:
        event = Event.model_validate(event_data())
        with pytest.raises(ValidationError):
            event.actor_id = "someone_else"  # type: ignore[misc]

    def test_attributes_accept_flat_scalars_only(self) -> None:
        event = Event.model_validate(event_data(attributes={"karma": 10, "flair": "x"}))
        assert event.attributes == {"karma": 10, "flair": "x"}
        with pytest.raises(ValidationError):
            Event.model_validate(event_data(attributes={"nested": {"a": 1}}))


class TestBlocksMatchEventType:
    def test_content_created_requires_content(self) -> None:
        with pytest.raises(ValidationError, match="requires 'content'"):
            Event.model_validate(event_data(content=None))

    def test_interaction_requires_interaction_and_target(self) -> None:
        base = event_data(event_type="INTERACTION", content=None)
        with pytest.raises(ValidationError, match="requires 'interaction'"):
            Event.model_validate(base | {"target": {"type": "content", "id": "p1"}})
        with pytest.raises(ValidationError, match="requires 'target'"):
            Event.model_validate(base | {"interaction": {"kind": "vote_up"}})

    def test_valid_interaction(self) -> None:
        event = Event.model_validate(
            event_data(
                event_type="INTERACTION",
                content=None,
                interaction={"kind": "vote_up"},
                target={"type": "content", "id": "p1", "owner_actor_id": "U1"},
            )
        )
        assert event.target is not None
        assert event.target.type is TargetType.CONTENT

    def test_block_not_allowed_on_other_event_type(self) -> None:
        with pytest.raises(ValidationError, match="'content' is not allowed"):
            Event.model_validate(event_data(event_type="ACCOUNT_CREATED", content={"kind": "post"}))

    def test_moderation_requires_moderation_block(self) -> None:
        with pytest.raises(ValidationError, match="requires 'moderation'"):
            Event.model_validate(event_data(event_type="MODERATION_ACTION", content=None))
        event = Event.model_validate(
            event_data(
                event_type="MODERATION_ACTION",
                content=None,
                moderation={"action": "remove_content", "source": "human"},
            )
        )
        assert event.moderation is not None

    def test_delete_must_target_content(self) -> None:
        base = event_data(event_type="CONTENT_DELETED", content=None)
        with pytest.raises(ValidationError, match="must target content"):
            Event.model_validate(base | {"target": {"type": "actor", "id": "U1"}})
        Event.model_validate(base | {"target": {"type": "content", "id": "p1"}})

    def test_account_created_needs_no_blocks(self) -> None:
        Event.model_validate(event_data(event_type="ACCOUNT_CREATED", content=None))


class TestContent:
    def test_domains_are_normalized_and_deduplicated(self) -> None:
        content = Content.model_validate(
            {"kind": "post", "url_domains": ["https://www.Bit.ly/x", "bit.ly", "EXAMPLE.com/a"]}
        )
        assert content.url_domains == ("bit.ly", "example.com")

    def test_text_hash_must_be_hex(self) -> None:
        Content.model_validate({"kind": "post", "text_hash": "a" * 64})
        # Raw text placed in text_hash by mistake must not be stored.
        with pytest.raises(ValidationError):
            Content.model_validate({"kind": "post", "text_hash": "Cheap phones! visit bit.ly"})

    @pytest.mark.parametrize("simhash", [-1, 2**64])
    def test_simhash_range(self, simhash: int) -> None:
        with pytest.raises(ValidationError):
            Content.model_validate({"kind": "post", "simhash": simhash})

    def test_language_is_lowercased(self) -> None:
        assert Content.model_validate({"kind": "post", "language": "PT-BR"}).language == "pt-br"
        with pytest.raises(ValidationError):
            Content.model_validate({"kind": "post", "language": "english"})

    def test_negative_counts_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Content.model_validate({"kind": "post", "length": -1})
        with pytest.raises(ValidationError):
            Content.model_validate({"kind": "post", "mention_count": -1})


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://www.Bit.ly/x?y=1", "bit.ly"),
            ("http://user:pw@example.com:8080/path", "example.com"),
            ("sub.example.co.uk.", "sub.example.co.uk"),
            ("EXAMPLE.COM#frag", "example.com"),
            ("bücher.de", "xn--bcher-kva.de"),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        assert normalize_domain(raw) == expected

    @pytest.mark.parametrize("raw", ["", "localhost", "not a domain", "https://"])
    def test_rejects_invalid(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_domain(raw)
