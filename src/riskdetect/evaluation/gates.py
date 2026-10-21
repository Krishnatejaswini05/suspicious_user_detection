"""Evaluation settings and pass/fail gates (configs/evaluation.yaml).

A new rules or model version is accepted only if every gate passes, so a change that
is "better on average but unfair to new accounts" cannot slip through.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from riskdetect.evaluation.metrics import Metrics
from riskdetect.evaluation.segments import NEW_ACCOUNTS, SegmentRate, rate_for

DEFAULT_EVALUATION_PATH = Path("configs/evaluation.yaml")


class EvaluationConfigError(ValueError):
    """The evaluation file is missing or invalid."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GateConfig(_Model):
    min_recall: float = Field(ge=0, le=1)
    min_precision: float = Field(ge=0, le=1)
    min_average_precision: float = Field(ge=0, le=1)
    max_false_positive_rate: float = Field(ge=0, le=1)
    max_new_account_false_positive_rate: float = Field(ge=0, le=1)
    max_new_account_fpr_ratio: float = Field(ge=1)
    must_beat_baselines: tuple[str, ...] = ()


class EvaluationConfig(_Model):
    version: int = Field(ge=1)
    test_days: int = Field(ge=1)
    precision_at: tuple[int, ...] = (10, 50, 100)
    seed: int = 0
    gates: GateConfig


def load_evaluation_config(path: Path = DEFAULT_EVALUATION_PATH) -> EvaluationConfig:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvaluationConfigError(f"Evaluation file not found: {path}") from exc
    try:
        return EvaluationConfig.model_validate(data)
    except ValidationError as exc:
        raise EvaluationConfigError(f"Invalid evaluation file {path}:\n{exc}") from exc


@dataclass(frozen=True)
class GateResult:
    name: str
    value: float | None
    threshold: float
    passed: bool


def check_gates(
    overall: Metrics,
    segments: list[SegmentRate],
    baselines: dict[str, Metrics],
    gates: GateConfig,
) -> list[GateResult]:
    def at_least(name: str, value: float | None, threshold: float) -> GateResult:
        return GateResult(name, value, threshold, value is not None and value >= threshold)

    def at_most(name: str, value: float | None, threshold: float) -> GateResult:
        # No innocent snapshots in a group means nobody could be wrongly flagged there.
        return GateResult(name, value, threshold, value is None or value <= threshold)

    results = [
        at_least("recall", overall.recall, gates.min_recall),
        at_least("precision", overall.precision, gates.min_precision),
        at_least("average precision", overall.average_precision, gates.min_average_precision),
        at_most("false positive rate", overall.false_positive_rate, gates.max_false_positive_rate),
    ]
    new = rate_for(segments, NEW_ACCOUNTS)
    new_fpr = new.false_positive_rate if new else None
    results.append(
        at_most(
            "new-account false positive rate", new_fpr, gates.max_new_account_false_positive_rate
        )
    )
    overall_fpr = overall.false_positive_rate
    ratio = None if not new_fpr or not overall_fpr else new_fpr / overall_fpr
    results.append(at_most("new-account / overall FPR", ratio, gates.max_new_account_fpr_ratio))
    for name in gates.must_beat_baselines:
        baseline = baselines.get(name)
        best = baseline.average_precision if baseline else None
        mine = overall.average_precision
        results.append(
            GateResult(
                f"beats {name} (average precision)",
                mine,
                best if best is not None else 0.0,
                mine is not None and (best is None or mine > best),
            )
        )
    return results
