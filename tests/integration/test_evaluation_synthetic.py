"""The report card end to end, on the tiny simulated world."""

from datetime import timedelta
from pathlib import Path

import pytest

from riskdetect.evaluation import evaluate, load_evaluation_config
from riskdetect.evaluation.__main__ import main
from riskdetect.features import compute_snapshots, daily_snapshots
from riskdetect.ingestion import default_pipeline, ingest_platform
from riskdetect.labels import truths_from_answer_key
from riskdetect.rules import load_rules
from riskdetect.scoring import Scorer, load_scoring_config
from riskdetect.storage import DataPaths, ParquetEventStore, ParquetFeatureStore
from riskdetect.synthetic import SimulationResult, write_simulation
from riskdetect.synthetic.writer import ANSWER_KEY_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = PROJECT_ROOT / "configs"
PLATFORMS = ["synthetic_forum", "synthetic_chat", "synthetic_market"]


@pytest.fixture(scope="module")
def data_root(tiny_result: SimulationResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("evaluation")
    write_simulation(tiny_result, root / "data")
    paths = DataPaths(root / "data")
    pipeline = default_pipeline(paths)
    store = ParquetEventStore(paths.events)
    features = ParquetFeatureStore(paths.features)
    times = daily_snapshots(
        tiny_result.scenario.start, tiny_result.scenario.end - timedelta(days=1)
    )
    for platform in PLATFORMS:
        ingest_platform(
            platform, pipeline=pipeline, config_dir=CONFIGS / "platforms", base_dir=root
        )
        features.write(platform, compute_snapshots(store, platform, times))
    return paths.root


def test_report_card(data_root: Path) -> None:
    features = ParquetFeatureStore(DataPaths(data_root).features)
    config = load_evaluation_config(CONFIGS / "evaluation.yaml").model_copy(update={"test_days": 3})
    report = evaluate(
        {p: features.read(p) for p in PLATFORMS},
        truths_from_answer_key(data_root / ANSWER_KEY_PATH),
        Scorer(load_rules(CONFIGS / "rules.yaml"), load_scoring_config(CONFIGS / "scoring.yaml")),
        config,
    )
    assert report.overall.positives > 0
    assert report.overall.false_positive_rate == 0
    assert report.overall.precision == 1.0
    detector_ap = report.overall.average_precision
    age_ap = report.baselines["age_only"].average_precision
    assert detector_ap is not None and age_ap is not None
    assert age_ap < detector_ap
    assert set(report.per_platform) == set(PLATFORMS)
    markdown = report.to_markdown()
    assert "## Gates" in markdown
    assert "Compared with lazy shortcuts" in markdown


def test_command_line_writes_the_report(data_root: Path) -> None:
    args = ["--data", str(data_root), "--config-dir", str(CONFIGS / "platforms")]
    args += ["--rules", str(CONFIGS / "rules.yaml"), "--scoring", str(CONFIGS / "scoring.yaml")]
    args += ["--evaluation", str(CONFIGS / "evaluation.yaml")]
    status = main(args)
    report = (data_root / "reports" / "evaluation.md").read_text(encoding="utf-8")
    assert report.startswith("# Detector evaluation")
    assert status in (0, 1)  # 1 means a gate failed; the tiny world is too small to judge
