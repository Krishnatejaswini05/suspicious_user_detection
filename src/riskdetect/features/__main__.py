"""Compute daily feature snapshots for stored events.

    python -m riskdetect.features                      # every configured platform
    python -m riskdetect.features --platform synthetic_forum --days 28

Writes data/features/platform=<p>/snapshots.parquet and percentiles.json.
Percentiles here are fitted on all computed snapshots, which is fine for
exploring data; training (a later milestone) fits them on the training period only.
"""

import argparse
from datetime import timedelta
from pathlib import Path

from riskdetect.adapters import DEFAULT_CONFIG_DIR, available_platforms, load_platform_config
from riskdetect.features.availability import fields_from_config, supported_features
from riskdetect.features.batch import compute_snapshots, daily_snapshots
from riskdetect.features.normalization import fit_percentiles
from riskdetect.rules.lists import DEFAULT_BLOCKED_DOMAINS_PATH, load_domain_list
from riskdetect.storage import DEFAULT_DATA_ROOT, DataPaths, ParquetEventStore, ParquetFeatureStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m riskdetect.features", description="Compute daily feature snapshots."
    )
    parser.add_argument("--platform", action="append", help="platform (repeatable)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--blocked-domains", type=Path, default=DEFAULT_BLOCKED_DOMAINS_PATH)
    parser.add_argument(
        "--days", type=int, default=28, help="days of snapshots, ending at the data"
    )
    args = parser.parse_args(argv)

    paths = DataPaths(args.data)
    events = ParquetEventStore(paths.events)
    features = ParquetFeatureStore(paths.features)
    blocked = load_domain_list(args.blocked_domains)
    for platform in args.platform or available_platforms(args.config_dir):
        newest = events.max_occurred_at(platform)
        if newest is None:
            print(f"{platform}: no stored events, skipped")
            continue
        fields = fields_from_config(load_platform_config(args.config_dir / f"{platform}.yaml"))
        times = daily_snapshots(newest - timedelta(days=args.days), newest)
        rows = compute_snapshots(
            events, platform, times, available_fields=fields, blocked_domains=blocked
        )
        table = fit_percentiles(platform, rows)
        features.write(platform, table.add_columns(rows))
        table.save(features.path(platform, "percentiles").with_suffix(".json"))
        supported = len(supported_features(fields))
        print(
            f"{platform}: {len(rows):,} rows, {len({r['actor_id'] for r in rows}):,} actors, "
            f"{len(times)} snapshots, {supported} of {len(supported_features(None))} features "
            f"supported -> {features.path(platform)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
