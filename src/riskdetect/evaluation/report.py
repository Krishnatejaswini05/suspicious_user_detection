"""The report card: everything measured, as one readable Markdown document."""

from dataclasses import dataclass, field
from datetime import datetime

from riskdetect.evaluation.gates import GateResult
from riskdetect.evaluation.metrics import Metrics
from riskdetect.evaluation.segments import SegmentRate
from riskdetect.evaluation.speed import SpeedSummary


@dataclass
class EvaluationReport:
    test_from: datetime
    test_to: datetime
    rules_version: int
    scoring_version: int
    overall: Metrics
    per_platform: dict[str, Metrics]
    baselines: dict[str, Metrics]
    segments: list[SegmentRate]
    gates: list[GateResult]
    speed: list[SpeedSummary] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(gate.passed for gate in self.gates)

    def to_markdown(self) -> str:
        verdict = "PASSED" if self.passed else "FAILED"
        out = [
            "# Detector evaluation",
            "",
            f"**Result: {verdict}** - rules v{self.rules_version}, scoring v{self.scoring_version}",
            "",
            f"Test period: {self.test_from:%Y-%m-%d} to {self.test_to:%Y-%m-%d} (daily snapshots). "
            "Percentiles were fitted on earlier days only.",
            "",
            "## Gates",
            "",
            "| Gate | Value | Threshold | |",
            "|---|---|---|---|",
        ]
        for g in self.gates:
            verdict = "pass" if g.passed else "FAIL"
            out.append(f"| {g.name} | {_fmt(g.value)} | {_fmt(g.threshold)} | {verdict} |")
        out += [
            "",
            "## Accuracy",
            "",
            _metrics_table({"all platforms": self.overall, **self.per_platform}),
        ]
        out += [
            "",
            "## Compared with lazy shortcuts",
            "",
            "Baselines flag the same number of snapshots as the detector, so their false-alarm "
            "rates are directly comparable.",
            "",
            _metrics_table({"detector": self.overall, **self.baselines}),
        ]
        out += [
            "",
            "## False alarms by group",
            "",
            "| Group | Innocent snapshots | Wrongly flagged | Rate |",
            "|---|---|---|---|",
        ]
        for s in self.segments:
            rate = _fmt(s.false_positive_rate)
            out.append(f"| {s.segment} | {s.negatives:,} | {s.false_positives:,} | {rate} |")
        if self.speed:
            out += [
                "",
                "## Speed (live replay)",
                "",
                "Minutes from each bad user's first abusive post to their first REVIEW/HIGH flag.",
                "",
                "| Group | Caught | Median minutes | Max minutes | Median posts before flag |",
                "|---|---|---|---|---|",
            ]
            out += [
                f"| {s.segment} | {s.caught}/{s.total} | {_fmt(s.median_minutes, 1)} | "
                f"{_fmt(s.max_minutes, 1)} | {_fmt(s.median_posts_before, 0)} |"
                for s in self.speed
            ]
        if self.notes:
            out += ["", "## Notes", ""] + [f"- {note}" for note in self.notes]
        return "\n".join(out) + "\n"


def _fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _metrics_table(rows: dict[str, Metrics]) -> str:
    lines = [
        "| | Snapshots | Bad | Flagged | Precision | Recall | False pos. rate | Avg precision |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, m in rows.items():
        lines.append(
            f"| {name} | {m.n:,} | {m.positives:,} | {m.flagged:,} | {_fmt(m.precision)} | "
            f"{_fmt(m.recall)} | {_fmt(m.false_positive_rate, 4)} | {_fmt(m.average_precision)} |"
        )
    return "\n".join(lines)
