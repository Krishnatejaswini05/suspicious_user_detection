"""Run scenarios through the live detector and check each expected outcome.

The "normal" of the scenario platform (percentiles, the population model) is learned
once from a separate reference crowd, as on a real platform, and never from the users
under test. Each scenario's events are then fed in time order to the same
RealtimeProcessor the server uses, and every score it produces is recorded.

The learned classifier is left out on purpose: it is trained on the simulator, so
including it would test the simulator against itself.
"""

import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import cast

from riskdetect.features import compute_snapshots, fit_percentiles
from riskdetect.features.batch import FeatureRow, daily_snapshots
from riskdetect.features.normalization import PercentileTable
from riskdetect.models import PopulationAnomaly, SelfBaselineAnomaly
from riskdetect.realtime import RealtimeProcessor
from riskdetect.rules import DEFAULT_RULES_PATH, load_rules
from riskdetect.rules.lists import DEFAULT_BLOCKED_DOMAINS_PATH, load_domain_list
from riskdetect.scenarios import behaviours as b
from riskdetect.scenarios.library import SCENARIOS, Expect, Scenario, crowd
from riskdetect.scenarios.world import ACTION_DAY, PLATFORM, World, at
from riskdetect.schema import Event, EventType
from riskdetect.scoring import (
    DEFAULT_SCORING_PATH,
    RiskResult,
    Scorer,
    SignalSource,
    Tier,
    load_scoring_config,
)
from riskdetect.storage import EventStore

_FLAGGED = frozenset({Tier.REVIEW, Tier.HIGH})


@dataclass(frozen=True)
class Detector:
    scorer: Scorer
    percentiles: PercentileTable
    blocked_domains: frozenset[str]


@dataclass(frozen=True)
class Outcome:
    expect: Expect
    met: bool
    detail: str


@dataclass
class ScenarioResult:
    scenario: Scenario
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(o.met for o in self.outcomes)

    @property
    def status(self) -> str:
        if self.scenario.known_gap is None:
            return "pass" if self.passed else "FAIL"
        return "gap now handled" if self.passed else "known gap"


class _Events:
    """Just enough of an event store for batch feature snapshots."""

    def __init__(self, events: list[Event]) -> None:
        self.events = events

    def iter_events(
        self,
        platform: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator[Event]:
        for event in self.events:
            if (start is None or event.occurred_at >= start) and (
                end is None or event.occurred_at < end
            ):
                yield event


@cache
def reference_detector(
    rules_path: Path = DEFAULT_RULES_PATH,
    scoring_path: Path = DEFAULT_SCORING_PATH,
    blocked_path: Path = DEFAULT_BLOCKED_DOMAINS_PATH,
) -> Detector:
    """The detector as deployed on the scenario platform, with "normal" learned from a crowd."""
    world = World(seed=0)
    for i in range(150):
        actor = f"ref{i}"
        world.signup(actor, at(-500 + 3 * i))
        style = i % 6
        b.ordinary(
            world,
            actor,
            0,
            ACTION_DAY,
            sessions=(0.4, 0.8, 1.2, 2.0, 3.5, 6.0)[style],
            actions=(2, 3, 4, 5, 6, 8)[style],
            write_share=(0.1, 0.3, 0.45, 0.5, 0.55, 0.6)[style],
            link_rate=(0.02, 0.05, 0.08, 0.12, 0.2, 0.3)[style],
        )
    events = world.sorted_events()
    store = cast(EventStore, _Events(events))  # only iter_events is used
    times = daily_snapshots(events[0].occurred_at, at(ACTION_DAY - 1))
    rows = compute_snapshots(store, PLATFORM, [t for t in times if t <= at(ACTION_DAY)])
    table = fit_percentiles(PLATFORM, rows)
    with_pct: list[FeatureRow] = table.add_columns(rows)
    models: list[SignalSource] = [
        SelfBaselineAnomaly(),
        PopulationAnomaly.fit({PLATFORM: with_pct}, seed=0),
    ]
    scorer = Scorer(load_rules(rules_path), load_scoring_config(scoring_path), models=models)
    return Detector(scorer, table, load_domain_list(blocked_path))


def run_scenario(scenario: Scenario, detector: Detector | None = None) -> ScenarioResult:
    detector = detector or reference_detector()
    world = World(seed=zlib.crc32(scenario.name.encode()))
    crowd(world)
    expectations = scenario.build(world)

    events = world.sorted_events()
    timeline: dict[str, list[RiskResult]] = {}
    scorer = detector.scorer
    if scenario.allowlist:
        allowlist = [(PLATFORM, actor) for actor in scenario.allowlist]
        scorer = Scorer(scorer.rules, scorer.config, allowlist, scorer.models)
    processor = RealtimeProcessor(
        scorer,
        percentiles={PLATFORM: detector.percentiles},
        blocked_domains=detector.blocked_domains,
        on_result=lambda r: timeline.setdefault(r.actor_id, []).append(r),
    )
    for event in events:
        processor.process(event)
    processor.flush()

    result = ScenarioResult(scenario)
    for expect in expectations:
        # The clock for "caught within" starts at each user's first action in the window.
        first: dict[str, datetime] = {}
        for event in events:
            if (
                event.actor_id in expect.actors
                and event.occurred_at >= expect.start
                and event.event_type is not EventType.ACCOUNT_CREATED  # signing up is not acting
            ):
                first.setdefault(event.actor_id, event.occurred_at)
        result.outcomes.append(_judge(expect, timeline, first))
    return result


def _judge(
    expect: Expect, timeline: dict[str, list[RiskResult]], first_action: dict[str, datetime]
) -> Outcome:
    if not expect.caught:
        offenders = []
        for actor in expect.actors:
            for r in timeline.get(actor, []):
                in_window = r.as_of >= expect.start and (
                    expect.until is None or r.as_of < expect.until
                )
                if in_window and r.tier in _FLAGGED:
                    offenders.append((actor, r))
                    break
        if not offenders:
            top = max(
                (
                    r
                    for a in expect.actors
                    for r in timeline.get(a, [])
                    if r.as_of >= expect.start and (expect.until is None or r.as_of < expect.until)
                ),
                key=lambda r: r.score,
                default=None,
            )
            peak = f"highest {top.tier} ({top.score:.2f})" if top else "never scored"
            return Outcome(expect, True, f"not flagged; {peak}")
        actor, r = offenders[0]
        why = r.reasons[0].text if r.reasons else "no reason"
        return Outcome(
            expect,
            False,
            f"{len(offenders)} flagged; {actor} reached {r.tier} ({r.score:.2f}) on "
            f"{r.as_of:%Y-%m-%d %H:%M}: {why}",
        )

    delays: list[timedelta] = []
    missed: list[tuple[str, RiskResult | None, str]] = []
    first_reason = ""
    for actor in expect.actors:
        began = first_action.get(actor, expect.start)
        deadline = began + (expect.within or timedelta(0))
        hit = next(
            (r for r in timeline.get(actor, []) if r.as_of >= began and r.tier in _FLAGGED),
            None,
        )
        if hit is not None and hit.as_of <= deadline:
            delays.append(hit.as_of - began)
            first_reason = first_reason or (hit.reasons[0].code if hit.reasons else "")
        else:
            late = (
                f", flagged only after {(hit.as_of - began).total_seconds() / 3600:.0f} h"
                if hit
                else ""
            )
            best = max(timeline.get(actor, []), key=lambda r: r.score, default=None)
            missed.append((actor, best, late))
    share = len(delays) / len(expect.actors)
    met = share >= expect.share
    if delays:
        slowest = max(delays).total_seconds() / 3600
        detail = (
            f"{len(delays)}/{len(expect.actors)} caught, "
            f"slowest after {slowest:.1f} h ({first_reason})"
        )
    else:
        detail = "none caught"
    if missed:
        actor, best, late = missed[0]
        peak = f"{best.tier} ({best.score:.2f})" if best else "never scored"
        detail += f"; missed e.g. {actor}, highest {peak}{late}"
    return Outcome(expect, met, detail)


def run_all(scenarios: list[Scenario] | None = None) -> list[ScenarioResult]:
    detector = reference_detector()
    return [run_scenario(s, detector) for s in (scenarios or SCENARIOS)]


def to_markdown(results: list[ScenarioResult]) -> str:
    lines = [
        "# Scenario library",
        "",
        "| Status | Scenario | Kind | Story | Expected | What happened |",
        "|---|---|---|---|---|---|",
    ]
    for res in results:
        for i, outcome in enumerate(res.outcomes):
            first = i == 0
            lines.append(
                "| "
                + " | ".join(
                    [
                        res.status if first else "",
                        res.scenario.name if first else "",
                        res.scenario.kind if first else "",
                        res.scenario.story if first else "",
                        outcome.expect.describe(),
                        ("✓ " if outcome.met else "✗ ") + outcome.detail,
                    ]
                )
                + " |"
            )
    gaps = [r for r in results if r.scenario.known_gap]
    if gaps:
        lines += ["", "## Known gaps", ""]
        lines += [f"- **{r.scenario.name}**: {r.scenario.known_gap}" for r in gaps]
    counts = {
        s: sum(r.status == s for r in results)
        for s in ("pass", "FAIL", "known gap", "gap now handled")
    }
    lines += ["", "Summary: " + ", ".join(f"{n} {s}" for s, n in counts.items() if n)]
    return "\n".join(lines) + "\n"
