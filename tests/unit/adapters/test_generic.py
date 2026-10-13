from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from riskdetect.adapters import (
    GenericAdapter,
    PlatformConfigError,
    parse_platform_config,
    run_adapter,
)
from riskdetect.schema import (
    ContentKind,
    Event,
    EventType,
    InteractionKind,
    Rejection,
    RejectionReason,
    TargetType,
    Visibility,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
SPAM = "Cheap phones! visit bit.ly/deal @buyer"

CSV = f"""listing_id,seller_id,action,created_time,category,description,price,target,target_owner
L1,S42,new_listing,2026-10-02 15:30,electronics,{SPAM},999,,
,S42,new_listing,2026-10-02 15:31,electronics,{SPAM},999,,
,S42,new_listing,2026-10-02 15:31,electronics,{SPAM},999,,
M1,S42,send_message,2026-10-02T10:05:00Z,,hello,,,
F1,U17,favorite,2026-10-02T11:00:00Z,,,,L1,S42
W1,U17,follow,2026-10-02T11:01:00Z,,,,S42,
X1,U17,teleport,2026-10-02T11:02:00Z,,,,,
T1,U17,new_listing,not-a-time,books,Old book,5,,
B1,,new_listing,2026-10-02T11:03:00Z,books,secret text,5,,
"""


def config_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "platform": "mini_market",
        "source": {"format": "csv", "path": "mini_market.csv", "timezone": "Asia/Kolkata"},
        "fields": {
            "event_id": "listing_id",
            "actor_id": "seller_id",
            "occurred_at": "created_time",
            "space_id": "category",
            "text": "description",
            "urls": "description",
            "target_id": "target",
            "target_owner_id": "target_owner",
            "attributes": ["price"],
        },
        "event_types": {
            "from_field": "action",
            "values": {
                "new_listing": "CONTENT_CREATED/listing",
                "send_message": {
                    "event_type": "CONTENT_CREATED",
                    "content_kind": "message",
                    "visibility": "private",
                },
                "favorite": "INTERACTION/save",
                "follow": "INTERACTION/follow",
            },
        },
    }
    data.update(overrides)
    return data


@pytest.fixture
def adapter(tmp_path: Path) -> GenericAdapter:
    (tmp_path / "mini_market.csv").write_text(CSV, encoding="utf-8")
    return GenericAdapter(parse_platform_config(config_data()), base_dir=tmp_path, now=NOW)


def run(adapter: GenericAdapter) -> list[Event | Rejection]:
    return list(run_adapter(adapter, adapter.new_report()))


def events(results: list[Event | Rejection]) -> list[Event]:
    return [r for r in results if isinstance(r, Event)]


def rejections(results: list[Event | Rejection]) -> list[Rejection]:
    return [r for r in results if isinstance(r, Rejection)]


class TestTranslation:
    def test_listing_becomes_content_event(self, adapter: GenericAdapter) -> None:
        listing = events(run(adapter))[0]
        assert listing.event_id == "mini_market:L1"
        assert listing.actor_id == "S42"
        assert listing.event_type is EventType.CONTENT_CREATED
        assert listing.space_id == "electronics"
        assert listing.attributes == {"price": "999"}
        assert listing.content is not None
        assert listing.content.kind is ContentKind.LISTING
        assert listing.content.url_domains == ("bit.ly",)
        assert listing.content.mention_count == 1
        assert listing.content.length == len(SPAM)
        assert listing.content.text_hash is not None
        assert listing.content.simhash is not None

    def test_naive_time_uses_platform_timezone(self, adapter: GenericAdapter) -> None:
        listing = events(run(adapter))[0]
        assert listing.occurred_at == datetime(2026, 10, 2, 10, 0, tzinfo=UTC)

    def test_full_form_mapping(self, adapter: GenericAdapter) -> None:
        message = next(e for e in events(run(adapter)) if e.event_id == "mini_market:M1")
        assert message.content is not None
        assert message.content.kind is ContentKind.MESSAGE
        assert message.content.visibility is Visibility.PRIVATE

    def test_interaction_with_target(self, adapter: GenericAdapter) -> None:
        by_id = {e.event_id: e for e in events(run(adapter))}
        favorite = by_id["mini_market:F1"]
        assert favorite.interaction is not None
        assert favorite.interaction.kind is InteractionKind.SAVE
        assert favorite.target is not None
        assert favorite.target.type is TargetType.CONTENT
        assert (favorite.target.id, favorite.target.owner_actor_id) == ("L1", "S42")
        follow = by_id["mini_market:W1"]
        assert follow.target is not None
        assert follow.target.type is TargetType.ACTOR

    def test_identical_rows_without_ids_stay_separate(self, adapter: GenericAdapter) -> None:
        # Rows 2 and 3 are the same spam at the same minute: two real posts, not a duplicate.
        derived = [e.event_id for e in events(run(adapter)) if ":d:" in e.event_id]
        assert len(derived) == 2
        assert len(set(derived)) == 2

    def test_reloading_gives_identical_ids(self, adapter: GenericAdapter) -> None:
        first = [e.event_id for e in events(run(adapter))]
        second = [e.event_id for e in events(run(adapter))]
        assert first == second


class TestRejections:
    def test_reasons(self, adapter: GenericAdapter) -> None:
        reasons = [r.reason for r in rejections(run(adapter))]
        assert reasons == [
            RejectionReason.UNMAPPED_ACTION,
            RejectionReason.INVALID_TIMESTAMP,
            RejectionReason.INVALID_STRUCTURE,  # missing seller_id
        ]

    def test_unmapped_action_names_the_value(self, adapter: GenericAdapter) -> None:
        unmapped = rejections(run(adapter))[0]
        assert "'teleport'" in unmapped.detail
        assert unmapped.fields == ("action",)

    def test_rejections_keep_the_record_but_not_its_text(self, adapter: GenericAdapter) -> None:
        for rejection in rejections(run(adapter)):
            assert rejection.raw is not None
            assert "description" not in rejection.raw
            assert "seller_id" in rejection.raw


class TestPrivacy:
    def test_raw_text_never_appears_in_events(self, adapter: GenericAdapter) -> None:
        for event in events(run(adapter)):
            dumped = event.model_dump_json()
            assert "Cheap phones" not in dumped
            assert "hello" not in dumped

    def test_unlisted_columns_are_not_copied(self, adapter: GenericAdapter) -> None:
        for event in events(run(adapter)):
            assert set(event.attributes) == {"price"}

    def test_pseudonymized_ids(self, tmp_path: Path) -> None:
        (tmp_path / "mini_market.csv").write_text(CSV, encoding="utf-8")
        config = parse_platform_config(config_data(privacy={"pseudonymize_ids": True}))
        adapter = GenericAdapter(config, base_dir=tmp_path, now=NOW, id_salt="s3cret")
        by_id = {e.event_id: e for e in events(run(adapter))}
        assert by_id["mini_market:L1"].actor_id.startswith("p_")
        favorite_target = by_id["mini_market:F1"].target
        assert favorite_target is not None
        # Content IDs stay readable; the owner (a person) is pseudonymized consistently.
        assert favorite_target.id == "L1"
        assert favorite_target.owner_actor_id == by_id["mini_market:L1"].actor_id
        follow_target = by_id["mini_market:W1"].target
        assert follow_target is not None and follow_target.id.startswith("p_")

    def test_pseudonymization_requires_a_salt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("RISKDETECT_ID_SALT", raising=False)
        config = parse_platform_config(config_data(privacy={"pseudonymize_ids": True}))
        with pytest.raises(PlatformConfigError, match="RISKDETECT_ID_SALT"):
            GenericAdapter(config, base_dir=tmp_path)


class TestReport:
    def test_counts(self, adapter: GenericAdapter) -> None:
        report = adapter.new_report()
        list(run_adapter(adapter, report))
        assert report.records_read == 9
        assert report.events_produced == 6
        assert report.rejected == 3
        assert report.event_types[EventType.CONTENT_CREATED] == 4
        assert report.event_types[EventType.INTERACTION] == 2

    def test_available_fields(self, adapter: GenericAdapter) -> None:
        report = adapter.new_report()
        list(run_adapter(adapter, report))
        assert {"text", "urls", "space_id", "content", "interactions"} <= set(
            report.available_fields
        )
        assert "reports" in report.unavailable_fields
        assert "language" not in report.available_fields
        assert report.missing_columns == []
        assert "Events produced:   6" in report.summary()

    def test_missing_column_warning(self, tmp_path: Path) -> None:
        (tmp_path / "mini_market.csv").write_text(CSV, encoding="utf-8")
        data = config_data()
        data["fields"] = {**data["fields"], "language": "lang"}
        adapter = GenericAdapter(parse_platform_config(data), base_dir=tmp_path, now=NOW)
        report = adapter.new_report()
        list(run_adapter(adapter, report))
        assert report.missing_columns == ["lang"]
        assert "WARNING" in report.summary()
