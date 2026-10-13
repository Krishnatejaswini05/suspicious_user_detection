from datetime import UTC, datetime
from pathlib import Path

import pytest

from riskdetect.synthetic import Scenario, SimulationResult, simulate

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TINY = Scenario(
    name="tiny",
    seed=7,
    start=datetime(2026, 8, 1, tzinfo=UTC),
    duration_days=7,
    platforms={"synthetic_forum": 40, "synthetic_chat": 30, "synthetic_market": 30},
    persona_mix={
        "normal": 0.70,
        "enthusiastic_new": 0.05,
        "power_user": 0.05,
        "lurker": 0.05,
        "spam_bot": 0.05,
        "slow_spammer": 0.05,
        "hijacked": 0.05,
    },
    noise_rate=0.01,
)


@pytest.fixture(scope="session")
def tiny_scenario() -> Scenario:
    return TINY


@pytest.fixture(scope="session")
def tiny_result() -> SimulationResult:
    return simulate(TINY)
