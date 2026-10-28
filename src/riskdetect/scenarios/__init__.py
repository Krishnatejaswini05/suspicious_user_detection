"""A library of situations the detector must handle, run through the live detector.

Each scenario builds a small simulated world (a crowd plus the users under test),
feeds it to the same live scoring the server uses, and checks an expected outcome:
innocent-but-unusual users are never sent to review; bad actors are, within a
stated time. See ``library.py`` for the situations.
"""

from riskdetect.scenarios.library import SCENARIOS, Expect, Scenario
from riskdetect.scenarios.runner import (
    ScenarioResult,
    reference_detector,
    run_all,
    run_scenario,
    to_markdown,
)

__all__ = [
    "SCENARIOS",
    "Expect",
    "Scenario",
    "ScenarioResult",
    "reference_detector",
    "run_all",
    "run_scenario",
    "to_markdown",
]
