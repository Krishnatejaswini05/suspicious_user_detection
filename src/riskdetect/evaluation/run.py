"""Run the whole exam: split, score, mark, compare, check gates."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from riskdetect.evaluation.baselines import baselines as make_baselines
from riskdetect.evaluation.gates import EvaluationConfig, check_gates
from riskdetect.evaluation.metrics import Metrics, Scored, compute_metrics
from riskdetect.evaluation.report import EvaluationReport
from riskdetect.evaluation.segments import false_positive_rates
from riskdetect.evaluation.speed import detections, summarize
from riskdetect.evaluation.splits import last_days_cutoff, refit_percentiles, time_split
from riskdetect.features import FeatureRow
from riskdetect.labels import LabeledRow, TruthIndex, label_rows
from riskdetect.scoring import Scorer, SignalSource, Tier
from riskdetect.storage import EventStore

_FLAGGED = frozenset({Tier.REVIEW, Tier.HIGH})

ModelFitter = Callable[[dict[str, list[FeatureRow]]], Sequence[SignalSource]]


def evaluate(
    snapshots: Mapping[str, list[FeatureRow]],
    truths: TruthIndex,
    scorer: Scorer,
    config: EvaluationConfig,
    *,
    history: Iterable[Mapping[str, Any]] = (),
    store: EventStore | None = None,
    fit_models: ModelFitter | None = None,
    holdout_platform: str | None = None,
) -> EvaluationReport:
    """Mark the detector on the last ``config.test_days`` days of each platform's snapshots.

    ``fit_models`` receives each platform's *training* snapshots (percentiles refitted on
    those same rows) and returns the models to score the test period with, so models
    never learn from the test period. ``history`` and ``store`` enable the speed section.

    ``holdout_platform`` tests transfer: models are fitted on the *other* platforms only,
    and only that platform's test snapshots are marked. (Its percentiles are still learned
    from its own earlier days, which needs no labels.)
    """
    all_rows = [row for rows in snapshots.values() for row in rows]
    if not all_rows:
        raise ValueError("no feature snapshots to evaluate")
    cutoff = last_days_cutoff(all_rows, config.test_days)

    labeled: list[LabeledRow] = []
    training: dict[str, list[FeatureRow]] = {}
    for platform, rows in sorted(snapshots.items()):
        train, test = time_split(rows, cutoff)
        if not test:
            continue
        if platform != holdout_platform:
            training[platform] = refit_percentiles(platform, train, train)
        if holdout_platform is None or platform == holdout_platform:
            labeled += label_rows(refit_percentiles(platform, train, test), truths)
    if not labeled:
        raise ValueError(f"no test snapshots for platform {holdout_platform!r}")
    if fit_models is not None:
        scorer = scorer.with_models(fit_models(training))

    scored = []
    for item in labeled:
        result = scorer.score(item.row)
        scored.append(Scored(result.score, result.tier in _FLAGGED, item.y))
    ks = config.precision_at
    overall = compute_metrics(scored, ks)
    per_platform = {
        platform: compute_metrics(
            [
                s
                for s, item in zip(scored, labeled, strict=True)
                if item.row["platform"] == platform
            ],
            ks,
        )
        for platform in sorted({item.row["platform"] for item in labeled})
    }
    baseline_metrics = _baselines(labeled, overall.flagged, config)
    segments = false_positive_rates(labeled, scored)
    speed = summarize(detections(history, truths, store)) if store is not None else []

    test_times = [item.row["as_of"] for item in labeled]
    return EvaluationReport(
        test_from=min(test_times),
        test_to=max(test_times),
        rules_version=scorer.rules.version,
        scoring_version=scorer.config.version,
        overall=overall,
        per_platform=per_platform,
        baselines=baseline_metrics,
        segments=segments,
        gates=check_gates(overall, segments, baseline_metrics, config.gates),
        speed=speed,
    )


def _baselines(
    labeled: list[LabeledRow], volume: int, config: EvaluationConfig
) -> dict[str, Metrics]:
    """Each baseline flags its top ``volume`` snapshots, as many as the detector flagged."""
    results = {}
    for name, baseline in make_baselines(config.seed).items():
        scores = [baseline(item.row) for item in labeled]
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        flagged = set(order[:volume])
        items = [Scored(scores[i], i in flagged, item.y) for i, item in enumerate(labeled)]
        results[name] = compute_metrics(items, config.precision_at)
    return results
