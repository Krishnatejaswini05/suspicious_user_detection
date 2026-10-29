"""Produce the detector's report card.

    python -m riskdetect.evaluation

Needs feature snapshots (`python -m riskdetect.features`) and the answer key
(`python -m riskdetect.synthetic`); live score history (`python -m riskdetect.realtime`)
adds the speed section. Writes data/reports/evaluation.md. Exits with status 1 if
any gate fails, so it can block a release in automation.
"""

import argparse
from pathlib import Path

from riskdetect.adapters import DEFAULT_CONFIG_DIR, available_platforms, platform_rule_packs
from riskdetect.evaluation.gates import DEFAULT_EVALUATION_PATH, load_evaluation_config
from riskdetect.evaluation.run import evaluate
from riskdetect.features import FeatureRow
from riskdetect.labels import truths_from_answer_key
from riskdetect.models import PopulationAnomaly, SelfBaselineAnomaly, train_classifier
from riskdetect.rules import DEFAULT_RULES_PATH, load_rules
from riskdetect.scoring import DEFAULT_SCORING_PATH, Scorer, SignalSource, load_scoring_config
from riskdetect.storage import (
    DEFAULT_DATA_ROOT,
    DataPaths,
    ParquetEventStore,
    ParquetFeatureStore,
    ParquetScoreStore,
)
from riskdetect.synthetic.writer import ANSWER_KEY_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m riskdetect.evaluation", description="Mark the detector."
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--scoring", type=Path, default=DEFAULT_SCORING_PATH)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION_PATH)
    parser.add_argument(
        "--rules-only", action="store_true", help="evaluate rules alone, without any models"
    )
    parser.add_argument(
        "--holdout-platform",
        help="train models on the other platforms and test only on this one (transfer test)",
    )
    args = parser.parse_args(argv)

    paths = DataPaths(args.data)
    features = ParquetFeatureStore(paths.features)
    scores = ParquetScoreStore(paths.scores)
    platforms = available_platforms(args.config_dir)
    snapshots = {p: rows for p in platforms if (rows := features.read(p))}
    history = [row for p in platforms for row in scores.read_history(p)]

    config = load_evaluation_config(args.evaluation)
    truths = truths_from_answer_key(paths.root / ANSWER_KEY_PATH)

    notes: list[str] = []

    def fit_models(training: dict[str, list[FeatureRow]]) -> list[SignalSource]:
        models: list[SignalSource] = [
            SelfBaselineAnomaly(),
            PopulationAnomaly.fit(training, seed=config.seed),
        ]
        rows = [row for platform_rows in training.values() for row in platform_rows]
        try:
            models.append(train_classifier(rows, truths))
        except ValueError as exc:  # e.g. no training period, or only one kind of label
            notes.append(f"Classifier not used: {exc}.")
        return models

    report = evaluate(
        snapshots,
        truths,
        Scorer(
            load_rules(args.rules),
            load_scoring_config(args.scoring),
            platform_packs=platform_rule_packs(args.config_dir),
        ),
        config,
        history=history,
        store=ParquetEventStore(paths.events) if history else None,
        fit_models=None if args.rules_only else fit_models,
        holdout_platform=args.holdout_platform,
    )
    report.notes.append(
        "Detectors: rules only."
        if args.rules_only
        else "Detectors: rules + self-baseline + population anomaly + classifier (models fitted "
        "on the training period only)."
    )
    report.notes += notes
    if args.holdout_platform:
        report.notes.append(
            f"Transfer test: models never saw {args.holdout_platform}; only its test period "
            "is marked."
        )
    report.notes.append(
        "Synthetic data: the rules were written knowing how the simulator behaves, so these "
        "numbers are an upper bound, not a promise for real platforms."
    )
    markdown = report.to_markdown()
    out = paths.root / "reports" / "evaluation.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Report written to {out}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
