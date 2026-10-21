"""Replay stored events through the live desk and record every live score.

    python -m riskdetect.realtime                      # every platform with stored events
    python -m riskdetect.realtime --platform synthetic_forum

Uses the percentiles saved by `python -m riskdetect.features`. Writes live score
history to data/scores/history/ and prints each escalation as it happens.
"""

import argparse
from collections import Counter
from pathlib import Path

from riskdetect.adapters import DEFAULT_CONFIG_DIR, available_platforms, load_platform_config
from riskdetect.features import PercentileTable, fields_from_config
from riskdetect.models import load_models
from riskdetect.realtime.policy import RescorePolicy
from riskdetect.realtime.processor import RealtimeProcessor
from riskdetect.realtime.replay import replay
from riskdetect.rules import DEFAULT_RULES_PATH, load_rules
from riskdetect.rules.lists import DEFAULT_BLOCKED_DOMAINS_PATH, load_domain_list
from riskdetect.scoring import (
    DEFAULT_SCORING_PATH,
    RiskResult,
    Scorer,
    Tier,
    load_scoring_config,
)
from riskdetect.storage import (
    DEFAULT_DATA_ROOT,
    DataPaths,
    ParquetEventStore,
    ParquetFeatureStore,
    ParquetScoreStore,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m riskdetect.realtime",
        description="Replay stored events through live scoring.",
    )
    parser.add_argument("--platform", action="append", help="platform (repeatable)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--scoring", type=Path, default=DEFAULT_SCORING_PATH)
    parser.add_argument("--blocked-domains", type=Path, default=DEFAULT_BLOCKED_DOMAINS_PATH)
    parser.add_argument("--every-events", type=int, default=RescorePolicy.every_events)
    parser.add_argument("--quiet", action="store_true", help="do not print each escalation")
    args = parser.parse_args(argv)

    paths = DataPaths(args.data)
    events = ParquetEventStore(paths.events)
    scores = ParquetScoreStore(paths.scores)
    features = ParquetFeatureStore(paths.features)
    models = load_models(paths.root / "models")
    scorer = Scorer(load_rules(args.rules), load_scoring_config(args.scoring), models=models)
    blocked = load_domain_list(args.blocked_domains)

    for platform in args.platform or available_platforms(args.config_dir):
        if events.count(platform) == 0:
            print(f"{platform}: no stored events, skipped")
            continue
        pct_path = features.path(platform, "percentiles").with_suffix(".json")
        percentiles = {platform: PercentileTable.load(pct_path)} if pct_path.exists() else {}
        if not percentiles:
            print(f"{platform}: no percentiles yet (run riskdetect.features); percentile rules off")
        fields = fields_from_config(load_platform_config(args.config_dir / f"{platform}.yaml"))

        results: list[RiskResult] = []

        def escalate(result: RiskResult, previous: Tier | None) -> None:
            if not args.quiet:
                reason = result.reasons[0].text if result.reasons else ""
                print(
                    f"  {result.as_of:%Y-%m-%d %H:%M} {result.actor_id} -> {result.tier}: {reason}"
                )

        processor = RealtimeProcessor(
            scorer,
            percentiles=percentiles,
            available_fields={platform: fields},
            blocked_domains=blocked,
            policy=RescorePolicy(every_events=args.every_events),
            on_result=results.append,
            on_escalation=escalate,
        )
        fed = replay(events, platform, processor)
        scores.append_history([r.to_row() for r in results])
        tiers = Counter(r.tier for r in processor.latest.values())
        counts = ", ".join(f"{tier} {tiers.get(tier, 0)}" for tier in Tier)
        print(f"{platform}: {fed:,} events, {len(results):,} live scores; latest tiers: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
