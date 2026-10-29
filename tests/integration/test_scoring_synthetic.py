"""End to end: simulate -> ingest -> features -> rules and scores.

The first working detector, checked against the simulator's answer key.
"""

from pathlib import Path

import pytest

from riskdetect.features import compute_snapshots, fit_percentiles
from riskdetect.features.__main__ import main as features_main
from riskdetect.ingestion import default_pipeline, ingest_platform
from riskdetect.rules import load_rules
from riskdetect.scoring import RiskResult, Scorer, Tier, load_scoring_config
from riskdetect.scoring.__main__ import main
from riskdetect.storage import DataPaths, ParquetEventStore, ParquetScoreStore
from riskdetect.synthetic import PersonaName, SimulationResult, write_simulation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = PROJECT_ROOT / "configs"
PLATFORMS = ["synthetic_forum", "synthetic_chat", "synthetic_market"]
FLAGGED = {Tier.REVIEW, Tier.HIGH}


@pytest.fixture(scope="module")
def data_root(tiny_result: SimulationResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("scoring")
    write_simulation(tiny_result, root / "data")
    pipeline = default_pipeline(DataPaths(root / "data"))
    for platform in PLATFORMS:
        ingest_platform(
            platform, pipeline=pipeline, config_dir=CONFIGS / "platforms", base_dir=root
        )
    return root / "data"


@pytest.fixture(scope="module")
def results(tiny_result: SimulationResult, data_root: Path) -> list[tuple[PersonaName, RiskResult]]:
    """Every user's score at the end of the simulation, with their true persona."""
    scorer = Scorer(load_rules(CONFIGS / "rules"), load_scoring_config(CONFIGS / "scoring.yaml"))
    store = ParquetEventStore(DataPaths(data_root).events)
    persona = {(e.label.platform, e.label.actor_id): e.persona for e in tiny_result.answer_key}
    out = []
    for platform in PLATFORMS:
        rows = compute_snapshots(store, platform, [tiny_result.scenario.end])
        rows = fit_percentiles(platform, rows).add_columns(rows)
        for result in scorer.score_all(rows):
            out.append((persona[(platform, result.actor_id)], result))
    return out


def test_spam_bots_are_flagged_with_reasons(
    results: list[tuple[PersonaName, RiskResult]],
) -> None:
    bots = [r for p, r in results if p is PersonaName.SPAM_BOT]
    assert bots
    assert all(r.tier in FLAGGED for r in bots)
    assert all(r.reasons for r in bots)


def test_enthusiastic_new_users_are_never_flagged(
    results: list[tuple[PersonaName, RiskResult]],
) -> None:
    newcomers = [r for p, r in results if p is PersonaName.ENTHUSIASTIC_NEW]
    assert newcomers
    assert all(r.tier is Tier.LOW for r in newcomers)


def test_no_innocent_user_reaches_review(
    results: list[tuple[PersonaName, RiskResult]],
) -> None:
    bad = {PersonaName.SPAM_BOT, PersonaName.SLOW_SPAMMER, PersonaName.HIJACKED}
    flagged_innocent = [(p, r.actor_id) for p, r in results if p not in bad and r.tier in FLAGGED]
    assert flagged_innocent == []


def test_command_line(data_root: Path) -> None:
    assert (
        features_main(["--data", str(data_root), "--config-dir", str(CONFIGS / "platforms")]) == 0
    )
    assert (
        main(
            [
                "--data",
                str(data_root),
                "--config-dir",
                str(CONFIGS / "platforms"),
                "--rules",
                str(CONFIGS / "rules"),
                "--scoring",
                str(CONFIGS / "scoring.yaml"),
            ]
        )
        == 0
    )
    stored = ParquetScoreStore(DataPaths(data_root).scores).read("synthetic_forum")
    assert stored
    assert {r["tier"] for r in stored} <= {t.value for t in Tier}
