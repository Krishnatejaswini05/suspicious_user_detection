"""Score users from their latest feature snapshot.

    python -m riskdetect.scoring                       # every platform with features
    python -m riskdetect.scoring --platform synthetic_forum --top 10

Reads data/features/platform=<p>/snapshots.parquet (from `python -m riskdetect.features`)
and writes data/scores/platform=<p>/scores.parquet.
"""

import argparse
from collections import Counter
from pathlib import Path

from riskdetect.adapters import DEFAULT_CONFIG_DIR, available_platforms
from riskdetect.rules import DEFAULT_RULES_PATH, load_rules
from riskdetect.scoring.config import DEFAULT_SCORING_PATH, load_scoring_config
from riskdetect.scoring.result import RiskResult, Tier
from riskdetect.scoring.scorer import Scorer
from riskdetect.storage import DEFAULT_DATA_ROOT, DataPaths, ParquetFeatureStore, ParquetScoreStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m riskdetect.scoring", description="Score users from their features."
    )
    parser.add_argument("--platform", action="append", help="platform (repeatable)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--scoring", type=Path, default=DEFAULT_SCORING_PATH)
    parser.add_argument(
        "--all-snapshots", action="store_true", help="score every snapshot, not only the latest"
    )
    parser.add_argument("--top", type=int, default=5, help="highest-risk users to print")
    args = parser.parse_args(argv)

    paths = DataPaths(args.data)
    features = ParquetFeatureStore(paths.features)
    scores = ParquetScoreStore(paths.scores)
    scorer = Scorer(load_rules(args.rules), load_scoring_config(args.scoring))

    for platform in args.platform or available_platforms(args.config_dir):
        rows = features.read(platform)
        if not rows:
            print(f"{platform}: no feature snapshots, skipped")
            continue
        if not args.all_snapshots:
            latest = max(row["as_of"] for row in rows)
            rows = [row for row in rows if row["as_of"] == latest]
        results = scorer.score_all(rows)
        scores.write(platform, [r.to_row() for r in results])
        _print_summary(platform, results, args.top)
    return 0


def _print_summary(platform: str, results: list[RiskResult], top: int) -> None:
    tiers = Counter(r.tier for r in results)
    counts = ", ".join(f"{tier} {tiers.get(tier, 0)}" for tier in Tier)
    print(f"{platform}: {len(results)} scored - {counts}")
    for result in sorted(results, key=lambda r: (-r.score, r.actor_id))[:top]:
        if result.tier is Tier.LOW:
            break
        print(
            f"  {result.actor_id} {result.tier} {result.score:.2f} "
            f"(confidence {result.confidence}, {result.as_of:%Y-%m-%d})"
        )
        for reason in result.reasons:
            print(f"    - {reason.text}")


if __name__ == "__main__":
    raise SystemExit(main())
