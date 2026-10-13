"""End to end: simulator -> raw files -> adapters -> ingestion -> event store."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from riskdetect.ingestion import default_pipeline, ingest_platform
from riskdetect.ingestion.__main__ import main
from riskdetect.schema import EventType, RejectionReason
from riskdetect.storage import DataPaths, ParquetEventStore
from riskdetect.synthetic import PersonaName, SimulationResult, write_simulation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = PROJECT_ROOT / "configs" / "platforms"
PLATFORMS = ["synthetic_forum", "synthetic_chat", "synthetic_market"]


@pytest.fixture(scope="module")
def loaded(
    tiny_result: SimulationResult, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, dict[str, tuple[int, int]]]:
    root = tmp_path_factory.mktemp("ingest")
    write_simulation(tiny_result, root / "data")
    pipeline = default_pipeline(DataPaths(root / "data"))
    counts = {}
    for platform in PLATFORMS:
        mapping, ingest = ingest_platform(
            platform, pipeline=pipeline, config_dir=CONFIGS, base_dir=root
        )
        counts[platform] = (mapping.events_produced, ingest.stored)
    return root, counts


def test_every_translated_event_is_stored(loaded: tuple[Path, dict[str, tuple[int, int]]]) -> None:
    root, counts = loaded
    store = ParquetEventStore(DataPaths(root / "data").events)
    for platform, (produced, stored) in counts.items():
        assert produced == stored > 0
        assert store.count(platform) == stored


def test_second_load_stores_nothing_new(
    loaded: tuple[Path, dict[str, tuple[int, int]]],
) -> None:
    root, counts = loaded
    pipeline = default_pipeline(DataPaths(root / "data"))
    for platform in PLATFORMS:
        _, again = ingest_platform(platform, pipeline=pipeline, config_dir=CONFIGS, base_dir=root)
        assert again.stored == 0
        assert again.duplicates == counts[platform][1]
        assert set(again.rejections) <= {RejectionReason.UNMAPPED_ACTION}


def test_point_in_time_history_of_a_spam_bot(
    tiny_result: SimulationResult, loaded: tuple[Path, dict[str, tuple[int, int]]]
) -> None:
    root, _ = loaded
    store = ParquetEventStore(DataPaths(root / "data").events)
    bot = next(
        e
        for e in tiny_result.answer_key
        if e.persona is PersonaName.SPAM_BOT and e.label.platform == "synthetic_forum"
    )
    abuse_start = bot.label.abuse_start
    assert abuse_start is not None
    before = store.get_actor_events("synthetic_forum", bot.label.actor_id, until=abuse_start)
    everything = store.get_actor_events("synthetic_forum", bot.label.actor_id)
    assert all(e.occurred_at < abuse_start for e in before)
    assert before[0].event_type is EventType.ACCOUNT_CREATED
    assert len(everything) > len(before)  # the spam came after abuse_start


def test_command_line(
    tiny_result: SimulationResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_simulation(tiny_result, tmp_path / "data")
    monkeypatch.chdir(tmp_path)  # platform YAML paths are relative to the project root
    assert main(["--platform", "synthetic_market", "--config-dir", str(CONFIGS)]) == 0
    assert ParquetEventStore(tmp_path / "data" / "events").count("synthetic_market") > 0
    assert datetime.now(UTC) > tiny_result.scenario.end
