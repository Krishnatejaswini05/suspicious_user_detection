"""The scenario library: every situation must turn out as expected.

Known gaps are expected to fail (strictly): when a change makes one pass, this test
fails too, as a reminder to remove its ``known_gap`` mark in the library.
"""

from pathlib import Path

import pytest

from riskdetect.scenarios import SCENARIOS, Scenario, reference_detector, run_scenario
from riskdetect.scenarios.runner import Detector
from riskdetect.scenarios.world import World

CONFIGS = Path(__file__).resolve().parents[2] / "configs"


@pytest.fixture(scope="module")
def detector() -> Detector:
    return reference_detector(
        CONFIGS / "rules.yaml", CONFIGS / "scoring.yaml", CONFIGS / "lists" / "blocked_domains.txt"
    )


CASES = [
    pytest.param(s, id=s.name, marks=pytest.mark.xfail(strict=True, reason=s.known_gap))
    if s.known_gap
    else pytest.param(s, id=s.name)
    for s in SCENARIOS
]


@pytest.mark.parametrize("scenario", CASES)
def test_scenario(scenario: Scenario, detector: Detector) -> None:
    result = run_scenario(scenario, detector)
    problems = [f"{o.expect.describe()}: {o.detail}" for o in result.outcomes if not o.met]
    assert not problems, "\n".join(problems)


def test_names_are_unique_and_both_kinds_are_covered() -> None:
    names = [s.name for s in SCENARIOS]
    assert len(names) == len(set(names))
    assert {s.kind for s in SCENARIOS} == {"innocent", "abuse"}
    assert all(s.story for s in SCENARIOS)


def test_worlds_are_reproducible() -> None:
    scenario = SCENARIOS[0]
    first, second = World(seed=5), World(seed=5)
    for world in (first, second):
        scenario.build(world)
    assert [e.model_dump() for e in first.events] == [e.model_dump() for e in second.events]
