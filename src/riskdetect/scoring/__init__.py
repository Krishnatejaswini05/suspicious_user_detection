"""Combine signals into one risk score, with confidence, tier, reasons and actions."""

from riskdetect.scoring.config import (
    DEFAULT_SCORING_PATH,
    ScoringConfig,
    ScoringConfigError,
    load_scoring_config,
)
from riskdetect.scoring.evidence import Evidence, Signal, SignalSource
from riskdetect.scoring.result import Confidence, RiskResult, Tier
from riskdetect.scoring.scorer import Scorer, combine, confidence_from, tier_from

__all__ = [
    "DEFAULT_SCORING_PATH",
    "Confidence",
    "Evidence",
    "RiskResult",
    "Scorer",
    "ScoringConfig",
    "ScoringConfigError",
    "Signal",
    "SignalSource",
    "Tier",
    "combine",
    "confidence_from",
    "load_scoring_config",
    "tier_from",
]
