from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conftest import EventFactory
from riskdetect.ingestion import CallbackPublisher, IngestionPipeline, check_lateness
from riskdetect.schema import Event, Rejection, RejectionReason
from riskdetect.storage import ParquetEventStore, ParquetQuarantineStore

T0 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 1, tzinfo=UTC)


class Recorder:
    def __init__(self) -> None:
        self.batches: list[list[Event]] = []

    def __call__(self, events: list[Event]) -> None:
        self.batches.append(events)

    @property
    def events(self) -> list[Event]:
        return [e for batch in self.batches for e in batch]


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def pipeline(tmp_path: Path, recorder: Recorder) -> IngestionPipeline:
    return IngestionPipeline(
        ParquetEventStore(tmp_path / "events"),
        ParquetQuarantineStore(tmp_path / "quarantine"),
        CallbackPublisher(recorder),
        clock=lambda: NOW,
    )


def test_stores_events_and_stamps_ingested_at(
    pipeline: IngestionPipeline, make_event: EventFactory
) -> None:
    report = pipeline.ingest("synthetic_forum", [make_event(), make_event()])
    assert (report.received, report.stored, report.duplicates) == (2, 2, 0)
    stored = list(pipeline.events.iter_events())
    assert all(e.ingested_at == NOW for e in stored)


def test_reloading_is_safe(pipeline: IngestionPipeline, make_event: EventFactory) -> None:
    events = [make_event(), make_event()]
    pipeline.ingest("synthetic_forum", events)
    again = pipeline.ingest("synthetic_forum", events)
    assert (again.stored, again.duplicates) == (0, 2)
    assert pipeline.events.count() == 2


def test_duplicates_within_one_load(pipeline: IngestionPipeline, make_event: EventFactory) -> None:
    event = make_event()
    report = pipeline.ingest("synthetic_forum", [event, event, event])
    assert (report.stored, report.duplicates) == (1, 2)


def test_repeated_behavior_is_not_a_duplicate(
    pipeline: IngestionPipeline, make_event: EventFactory
) -> None:
    # Same user, same text, same second, different event IDs: two real posts.
    same = {"occurred_at": T0, "content": {"kind": "post", "text_hash": "c" * 64}}
    report = pipeline.ingest("synthetic_forum", [make_event(**same), make_event(**same)])
    assert report.stored == 2


def test_rejections_are_quarantined(pipeline: IngestionPipeline, make_event: EventFactory) -> None:
    rejection = Rejection(RejectionReason.UNMAPPED_ACTION, "x", ("kind",), {"kind": "x"})
    report = pipeline.ingest("synthetic_forum", [make_event(), rejection])
    assert report.rejections == {RejectionReason.UNMAPPED_ACTION: 1}
    assert report.stored == 1
    assert [r.rejection for r in pipeline.quarantine.read("synthetic_forum")] == [rejection]


def test_only_new_events_are_published(
    pipeline: IngestionPipeline, make_event: EventFactory, recorder: Recorder
) -> None:
    first = make_event()
    pipeline.ingest("synthetic_forum", [first])
    report = pipeline.ingest("synthetic_forum", [first, make_event()])
    assert report.published == 1
    assert len(recorder.events) == 2


def test_works_across_batches(tmp_path: Path, make_event: EventFactory) -> None:
    pipeline = IngestionPipeline(
        ParquetEventStore(tmp_path / "events"),
        ParquetQuarantineStore(tmp_path / "quarantine"),
        batch_size=2,
        clock=lambda: NOW,
    )
    event = make_event()
    report = pipeline.ingest("synthetic_forum", [event, make_event(), make_event(), event])
    assert (report.stored, report.duplicates) == (3, 1)


def test_late_events_mark_actors_for_rescore(
    pipeline: IngestionPipeline, make_event: EventFactory
) -> None:
    first = pipeline.ingest("synthetic_forum", [make_event(occurred_at=T0)])
    assert first.late == 0  # first load: nothing to be late relative to

    report = pipeline.ingest(
        "synthetic_forum",
        [
            make_event(actor_id="u2", occurred_at=T0 - timedelta(hours=1)),
            make_event(actor_id="u3", occurred_at=T0 - timedelta(days=10)),
            make_event(actor_id="u4", occurred_at=T0 + timedelta(hours=1)),
        ],
    )
    assert (report.late, report.very_late) == (2, 1)
    assert report.actors_to_rescore == {"u2", "u3"}
    assert report.stored == 3  # late events are still stored


def test_wrong_platform_is_a_programming_error(
    pipeline: IngestionPipeline, make_event: EventFactory
) -> None:
    with pytest.raises(ValueError, match="synthetic_chat"):
        pipeline.ingest("synthetic_chat", [make_event()])  # a forum event sent to the chat pipeline


def test_check_lateness_without_watermark(make_event: EventFactory) -> None:
    assert check_lateness([make_event()], None).late == 0


def test_summary(pipeline: IngestionPipeline, make_event: EventFactory) -> None:
    report = pipeline.ingest("synthetic_forum", [make_event()])
    assert "Stored:            1" in report.summary()
