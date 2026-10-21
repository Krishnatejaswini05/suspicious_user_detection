"""Fit the models on stored feature snapshots.

    python -m riskdetect.models

Reads data/features/platform=<p>/snapshots.parquet (from `python -m riskdetect.features`)
and writes data/models/population_anomaly.json, plus data/models/classifier.json when
labels exist (data/labels/answer_key.parquet). Scoring and live scoring pick them up
automatically. (For a fair evaluation, `python -m riskdetect.evaluation` fits its own
copies on the training period only.)
"""

import argparse
from pathlib import Path

from riskdetect.adapters import DEFAULT_CONFIG_DIR, available_platforms
from riskdetect.labels import truths_from_answer_key
from riskdetect.models import (
    PopulationAnomaly,
    save_classifier,
    save_population_model,
    train_classifier,
)
from riskdetect.storage import DEFAULT_DATA_ROOT, DataPaths, ParquetFeatureStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m riskdetect.models", description="Fit the population anomaly model."
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    paths = DataPaths(args.data)
    features = ParquetFeatureStore(paths.features)
    rows = {p: r for p in available_platforms(args.config_dir) if (r := features.read(p))}
    model = PopulationAnomaly.fit(rows, seed=args.seed)
    path = save_population_model(model, paths.root / "models")
    fitted = ", ".join(f"{p} ({len(rows[p]):,} snapshots)" for p in sorted(model.platforms))
    print(f"Fitted population anomaly model for: {fitted or 'nothing'}")
    print(f"Saved to {path}")

    answer_key = paths.labels / "answer_key.parquet"
    if not answer_key.exists():
        print("No labels yet: the classifier was not trained.")
        return 0
    all_rows = [row for platform_rows in rows.values() for row in platform_rows]
    classifier = train_classifier(all_rows, truths_from_answer_key(answer_key))
    print(f"Trained classifier on {len(all_rows):,} snapshots")
    print(f"Saved to {save_classifier(classifier, paths.root / 'models')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
