"""The report card: how good and how fair the detector is, against the right answers."""

from riskdetect.evaluation.baselines import age_only, baselines, random_baseline, volume_only
from riskdetect.evaluation.gates import (
    DEFAULT_EVALUATION_PATH,
    EvaluationConfig,
    EvaluationConfigError,
    GateResult,
    check_gates,
    load_evaluation_config,
)
from riskdetect.evaluation.metrics import Metrics, Scored, average_precision, compute_metrics
from riskdetect.evaluation.report import EvaluationReport
from riskdetect.evaluation.run import evaluate
from riskdetect.evaluation.segments import NEW_ACCOUNTS, SegmentRate, false_positive_rates
from riskdetect.evaluation.speed import Detection, SpeedSummary, detections, summarize
from riskdetect.evaluation.splits import (
    last_days_cutoff,
    platform_holdout,
    refit_percentiles,
    time_split,
)

__all__ = [
    "DEFAULT_EVALUATION_PATH",
    "NEW_ACCOUNTS",
    "Detection",
    "EvaluationConfig",
    "EvaluationConfigError",
    "EvaluationReport",
    "GateResult",
    "Metrics",
    "Scored",
    "SegmentRate",
    "SpeedSummary",
    "age_only",
    "average_precision",
    "baselines",
    "check_gates",
    "compute_metrics",
    "detections",
    "evaluate",
    "false_positive_rates",
    "last_days_cutoff",
    "load_evaluation_config",
    "platform_holdout",
    "random_baseline",
    "refit_percentiles",
    "summarize",
    "time_split",
    "volume_only",
]
