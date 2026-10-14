"""End to end: simulated platforms -> stored events -> feature snapshots.

Checks that the features tell simulated bad actors apart from good ones,
including the hard-but-innocent enthusiastic new users.
"""

from pathlib import Path
from statistics import mean
from typing import Any

import pytest

from riskdetect.features import FeatureRow, compute_snapshots
from riskdetect.features.__main__ import main
from riskdetect.ingestion import default_pipeline, ingest_platform
from riskdetect.storage import DataPaths, ParquetEventStore, ParquetFeatureStore
from riskdetect.synthetic import PersonaName, SimulationResult, write_simulation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = PROJECT_ROOT / "configs" / "platforms"
BAD = {PersonaName.SPAM_BOT, PersonaName.SLOW_SPAMMER, PersonaName.HIJACKED}


@pytest.fixture(scope="module")
def data_root(tiny_result: SimulationResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("features")
    write_simulation(tiny_result, root / "data")
    pipeline = default_pipeline(DataPaths(root / "data"))
    for platform in ("synthetic_forum", "synthetic_chat", "synthetic_market"):
        ingest_platform(platform, pipeline=pipeline, config_dir=CONFIGS, base_dir=root)
    return root / "data"


@pytest.fixture(scope="module")
def final_rows(tiny_result: SimulationResult, data_root: Path) -> list[FeatureRow]:
    store = ParquetEventStore(DataPaths(data_root).events)
    return compute_snapshots(store, "synthetic_forum", [tiny_result.scenario.end])


def by_persona(
    rows: list[FeatureRow], result: SimulationResult, feature: str
) -> dict[PersonaName, float]:
    persona = {
        e.label.actor_id: e.persona
        for e in result.answer_key
        if e.label.platform == "synthetic_forum"
    }
    groups: dict[PersonaName, list[float]] = {}
    for row in rows:
        if row[feature] is not None:
            groups.setdefault(persona[row["actor_id"]], []).append(row[feature])
    return {name: mean(values) for name, values in groups.items()}


def test_duplicates_separate_bad_from_good(
    final_rows: list[FeatureRow], tiny_result: SimulationResult
) -> None:
    dup = by_persona(final_rows, tiny_result, "duplicate_ratio_7d")
    worst_good = max(v for p, v in dup.items() if p not in BAD)
    best_bad = min(v for p, v in dup.items() if p in BAD)
    assert worst_good < 0.1 < 0.5 < best_bad


def test_bots_are_machine_regular_but_new_humans_are_not(
    final_rows: list[FeatureRow], tiny_result: SimulationResult
) -> None:
    regularity = by_persona(final_rows, tiny_result, "timing_regularity")
    assert regularity[PersonaName.SPAM_BOT] > 0.8
    assert regularity[PersonaName.ENTHUSIASTIC_NEW] < 0.5


def test_new_innocent_users_look_new_but_not_spammy(
    final_rows: list[FeatureRow], tiny_result: SimulationResult
) -> None:
    age = by_persona(final_rows, tiny_result, "account_age_days")
    links = by_persona(final_rows, tiny_result, "link_ratio_7d")
    assert age[PersonaName.ENTHUSIASTIC_NEW] < 10  # as new as the spam bots...
    assert (
        links[PersonaName.ENTHUSIASTIC_NEW] < 0.3 < links[PersonaName.SPAM_BOT]
    )  # ...but different


def test_command_line_writes_snapshots_with_percentiles(data_root: Path) -> None:
    assert main(["--data", str(data_root), "--config-dir", str(CONFIGS), "--days", "7"]) == 0
    rows: list[dict[str, Any]] = ParquetFeatureStore(DataPaths(data_root).features).read(
        "synthetic_market"
    )
    assert rows
    assert all(0 <= r["posts_24h_pct"] <= 100 for r in rows if r["posts_24h_pct"] is not None)
    assert (
        DataPaths(data_root).features / "platform=synthetic_market" / "percentiles.json"
    ).exists()
