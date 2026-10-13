from pathlib import Path
from typing import Any

import pytest
import yaml

from riskdetect.adapters import (
    EventMapping,
    PlatformConfigError,
    load_platform_config,
    parse_platform_config,
)
from riskdetect.schema import ContentKind, EventType, InteractionKind, TargetType, Visibility

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def config_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "platform": "mini_market",
        "source": {"format": "csv", "path": "data/raw/mini_market.csv"},
        "fields": {"actor_id": "seller_id", "occurred_at": "created_time"},
        "event_types": {
            "from_field": "action",
            "values": {"new_listing": "CONTENT_CREATED/listing"},
        },
    }
    data.update(overrides)
    return data


class TestEventMapping:
    def test_shorthand(self) -> None:
        mapping = EventMapping.model_validate("CONTENT_CREATED/listing")
        assert mapping.event_type is EventType.CONTENT_CREATED
        assert mapping.content_kind is ContentKind.LISTING

    def test_shorthand_without_kind(self) -> None:
        assert EventMapping.model_validate("REPORT_FILED").event_type is EventType.REPORT_FILED

    def test_full_form(self) -> None:
        mapping = EventMapping.model_validate(
            {"event_type": "CONTENT_CREATED", "content_kind": "message", "visibility": "private"}
        )
        assert mapping.visibility is Visibility.PRIVATE

    @pytest.mark.parametrize(
        "value",
        [
            "CONTENT_CREATD/listing",  # typo in event type
            "CONTENT_CREATED/lsting",  # typo in kind
            "CONTENT_CREATED",  # kind missing
            "INTERACTION",  # kind missing
            "REPORT_FILED/post",  # kind does not apply
        ],
    )
    def test_mistakes_are_rejected(self, value: str) -> None:
        with pytest.raises(ValueError):
            EventMapping.model_validate(value)

    def test_default_targets(self) -> None:
        assert EventMapping.model_validate("INTERACTION/vote_up").resolved_target_type is (
            TargetType.CONTENT
        )
        follow = EventMapping.model_validate("INTERACTION/follow")
        assert follow.interaction_kind is InteractionKind.FOLLOW
        assert follow.resolved_target_type is TargetType.ACTOR
        assert EventMapping.model_validate("ACCOUNT_CREATED").resolved_target_type is None
        reply = EventMapping.model_validate("CONTENT_CREATED/reply")
        assert reply.resolved_target_type is TargetType.CONTENT


class TestPlatformConfig:
    def test_minimal_config(self) -> None:
        config = parse_platform_config(config_data())
        assert config.source.timezone == "UTC"
        assert config.fields.attributes == ()
        assert not config.privacy.pseudonymize_ids

    def test_typo_in_field_name_is_reported_with_location(self) -> None:
        data = config_data(fields={"actor_idd": "seller_id", "occurred_at": "created_time"})
        with pytest.raises(PlatformConfigError, match=r"fields.actor_idd"):
            parse_platform_config(data)

    def test_typo_in_event_type_is_reported_with_location(self) -> None:
        data = config_data(
            event_types={"from_field": "action", "values": {"x": "CONTENT_CREATD/listing"}}
        )
        with pytest.raises(PlatformConfigError, match=r"event_types\.values\.x"):
            parse_platform_config(data)

    @pytest.mark.parametrize(
        "change",
        [
            {"platform": "Mini-Market"},
            {"schema_version": 99},
            {"source": {"format": "xml", "path": "x"}},
            {"source": {"format": "csv", "path": "x", "timezone": "Mars/Base"}},
            {"overrides": {"scoring": {"threshold": 0.1}}},
            {"event_types": {"from_field": "action", "values": {}}},
        ],
    )
    def test_invalid_configs(self, change: dict[str, Any]) -> None:
        with pytest.raises(PlatformConfigError):
            parse_platform_config(config_data(**change))

    def test_rules_override_allowed(self) -> None:
        config = parse_platform_config(config_data(overrides={"rules": {"max_posts": 5}}))
        assert config.overrides == {"rules": {"max_posts": 5}}

    def test_referenced_columns(self) -> None:
        config = parse_platform_config(
            config_data(
                fields={
                    "actor_id": "seller_id",
                    "occurred_at": "created_time",
                    "text": "description",
                    "attributes": ["price"],
                }
            )
        )
        assert config.referenced_columns() == {
            "actor_id": "seller_id",
            "occurred_at": "created_time",
            "text": "description",
            "action": "action",
            "attributes.price": "price",
        }


class TestLoadFile:
    def test_load(self, tmp_path: Path) -> None:
        path = tmp_path / "mini_market.yaml"
        path.write_text(yaml.safe_dump(config_data()), encoding="utf-8")
        assert load_platform_config(path).platform == "mini_market"

    def test_file_name_must_match_platform(self, tmp_path: Path) -> None:
        path = tmp_path / "other_name.yaml"
        path.write_text(yaml.safe_dump(config_data()), encoding="utf-8")
        with pytest.raises(PlatformConfigError, match="must match the file name"):
            load_platform_config(path)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(PlatformConfigError, match="not found"):
            load_platform_config(tmp_path / "nope.yaml")

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("platform: [unclosed", encoding="utf-8")
        with pytest.raises(PlatformConfigError, match="not valid YAML"):
            load_platform_config(path)

    def test_template_is_a_valid_config(self) -> None:
        template = PROJECT_ROOT / "configs" / "platforms" / "_template.yaml"
        data = yaml.safe_load(template.read_text(encoding="utf-8"))
        config = parse_platform_config(data, source=str(template))
        assert config.event_types.values["dm"].visibility is Visibility.PRIVATE
