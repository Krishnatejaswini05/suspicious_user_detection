"""The innocent users copied from real data: experts who always link, and maintainers."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

import pytest

from riskdetect.schema import LabelCategory
from riskdetect.synthetic import PersonaName, Scenario, SimulationResult, simulate

SCENARIO = Scenario(
    name="hard_negatives",
    seed=11,
    start=datetime(2026, 8, 1, tzinfo=UTC),
    duration_days=14,
    platforms={"synthetic_forum": 20},
    persona_mix={"normal": 0.5, "expert_linker": 0.25, "maintainer": 0.25},
    noise_rate=0.0,
)


@pytest.fixture(scope="module")
def result() -> SimulationResult:
    return simulate(SCENARIO)


def posts_by_persona(result: SimulationResult) -> dict[PersonaName, list[dict[str, Any]]]:
    who = {e.label.actor_id: e.persona for e in result.answer_key}
    out: dict[PersonaName, list[dict[str, Any]]] = defaultdict(list)
    for row in result.rows["synthetic_forum"]:
        if row["kind"] in ("submission", "comment"):
            out[who[row["author"]]].append(row)
    return out


def test_both_are_innocent(result: SimulationResult) -> None:
    for entry in result.answer_key:
        assert entry.label.category is LabelCategory.CLEAN
        assert entry.label.abuse_start is None


def test_experts_link_far_more_than_normal_users(result: SimulationResult) -> None:
    posts = posts_by_persona(result)

    def link_share(persona: PersonaName) -> float:
        rows = posts[persona]
        return sum("https://" in (r["body"] or "") for r in rows) / len(rows)

    assert link_share(PersonaName.EXPERT_LINKER) > 0.6 > 0.2 > link_share(PersonaName.NORMAL)


def test_maintainers_have_a_day_of_moved_notices_without_exact_repeats(
    result: SimulationResult,
) -> None:
    notices = [
        r
        for r in posts_by_persona(result)[PersonaName.MAINTAINER]
        if "moved" in r["body"] or "no longer works" in r["body"]
    ]
    per_author_day = Counter((r["author"], r["ts"][:10]) for r in notices)
    assert max(per_author_day.values()) >= 5  # a whole day of them
    bodies = [r["body"] for r in notices]
    assert len(set(bodies)) == len(bodies)  # a new page and context every time
