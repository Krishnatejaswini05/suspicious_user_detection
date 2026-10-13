from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from riskdetect.schema import Event
from riskdetect.synthetic import Scenario, SimulationResult, simulate

EventFactory = Callable[..., Event]

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


@pytest.fixture
def make_event() -> EventFactory:
    """Build a valid CONTENT_CREATED event; keyword arguments override any field."""
    counter = iter(range(1, 1_000_000))

    def factory(**overrides: Any) -> Event:
        n = next(counter)
        data: dict[str, Any] = {
            "event_id": f"synthetic_forum:e{n}",
            "platform": "synthetic_forum",
            "actor_id": "u1",
            "event_type": "CONTENT_CREATED",
            "occurred_at": datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            "content": {"kind": "post", "text_hash": f"{n:064x}"},
        }
        data.update(overrides)
        return Event.model_validate(data)

    return factory
