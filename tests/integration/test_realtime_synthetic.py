"""End to end, live: ingestion publishes each stored batch straight to the live desk.

simulate -> raw files -> adapters -> ingestion -> (publisher) -> realtime scoring
"""

from datetime import timedelta
from pathlib import Path

import pytest

from riskdetect.adapters import load_platform_config
from riskdetect.features import compute_snapshots, fields_from_config, fit_percentiles
from riskdetect.ingestion import CallbackPublisher, IngestionPipeline, ingest_platform
from riskdetect.realtime import RealtimeProcessor
from riskdetect.realtime.__main__ import main
from riskdetect.rules import load_rules
from riskdetect.rules.lists import load_domain_list
from riskdetect.scoring import RiskResult, Scorer, Tier, load_scoring_config
from riskdetect.storage import (
    DataPaths,
    ParquetEventStore,
    ParquetQuarantineStore,
    ParquetScoreStore,
)
from riskdetect.synthetic import PersonaName, SimulationResult, write_simulation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = PROJECT_ROOT / "configs"
PLATFORM = "synthetic_forum"
FLAGGED = {Tier.REVIEW, Tier.HIGH}


@pytest.fixture(scope="module")
def live(
    tiny_result: SimulationResult, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, list[RiskResult]]:
    root = tmp_path_factory.mktemp("live")
    write_simulation(tiny_result, root / "data")
    paths = DataPaths(root / "data")

    # Percentiles come from a first nightly batch over the same period (fine for a demo;
    # evaluation fits them on a separate training period).
    staging = ParquetEventStore(root / "staging_events")
    staging_pipeline = IngestionPipeline(staging, ParquetQuarantineStore(root / "staging_q"))
    ingest_platform(
        PLATFORM, pipeline=staging_pipeline, config_dir=CONFIGS / "platforms", base_dir=root
    )
    rows = compute_snapshots(staging, PLATFORM, [tiny_result.scenario.end])
    fields = fields_from_config(load_platform_config(CONFIGS / "platforms" / f"{PLATFORM}.yaml"))

    results: list[RiskResult] = []
    processor = RealtimeProcessor(
        Scorer(load_rules(CONFIGS / "rules"), load_scoring_config(CONFIGS / "scoring.yaml")),
        percentiles={PLATFORM: fit_percentiles(PLATFORM, rows)},
        available_fields={PLATFORM: fields},
        blocked_domains=load_domain_list(CONFIGS / "lists" / "blocked_domains.txt"),
        on_result=results.append,
    )
    pipeline = IngestionPipeline(
        ParquetEventStore(paths.events),
        ParquetQuarantineStore(paths.quarantine),
        CallbackPublisher(processor.on_events),
        batch_size=200,  # small batches: events reach the live desk as they are stored
    )
    ingest_platform(PLATFORM, pipeline=pipeline, config_dir=CONFIGS / "platforms", base_dir=root)
    results.extend(processor.flush())
    return root, results


def personas(result: SimulationResult) -> dict[str, PersonaName]:
    return {e.label.actor_id: e.persona for e in result.answer_key if e.label.platform == PLATFORM}


def test_spam_bots_are_caught_within_an_hour_of_their_first_burst(
    tiny_result: SimulationResult, live: tuple[Path, list[RiskResult]]
) -> None:
    root, results = live
    store = ParquetEventStore(DataPaths(root / "data").events)
    who = personas(tiny_result)
    start = {
        e.label.actor_id: e.label.abuse_start
        for e in tiny_result.answer_key
        if e.label.platform == PLATFORM
    }
    bots = [a for a, p in who.items() if p is PersonaName.SPAM_BOT]
    assert bots
    for bot in bots:
        abuse_start = start[bot]
        assert abuse_start is not None
        spam = [
            e.occurred_at
            for e in store.get_actor_events(PLATFORM, bot, since=abuse_start)
            if e.content is not None
        ]
        flags = [r.as_of for r in results if r.actor_id == bot and r.tier in FLAGGED]
        assert flags, f"{bot} was never flagged"
        assert min(flags) - spam[0] < timedelta(hours=1)


def test_innocent_users_are_never_flagged_even_for_a_moment(
    tiny_result: SimulationResult, live: tuple[Path, list[RiskResult]]
) -> None:
    _, results = live
    who = personas(tiny_result)
    bad = {PersonaName.SPAM_BOT, PersonaName.SLOW_SPAMMER, PersonaName.HIJACKED}
    assert not [r.actor_id for r in results if who[r.actor_id] not in bad and r.tier in FLAGGED]


def test_command_line_replays_and_records_history(live: tuple[Path, list[RiskResult]]) -> None:
    root, _ = live
    data = root / "data"
    args = ["--data", str(data), "--config-dir", str(CONFIGS / "platforms"), "--platform", PLATFORM]
    args += ["--rules", str(CONFIGS / "rules"), "--scoring", str(CONFIGS / "scoring.yaml")]
    args += ["--blocked-domains", str(CONFIGS / "lists" / "blocked_domains.txt"), "--quiet"]
    args += ["--warm-up-days", "2"]  # the tiny world is only a week long
    assert main(args) == 0
    history = ParquetScoreStore(DataPaths(data).scores).read_history(PLATFORM)
    assert history
    assert [r["as_of"] for r in history] == sorted(r["as_of"] for r in history)
