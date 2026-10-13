"""End to end: simulated raw files -> platform YAML -> adapters -> canonical Events.

This is the "new platform needs only a YAML file" promise in action: three
platforms with different columns, formats and time encodings are all read by
the same generic adapter, configured only by configs/platforms/*.yaml.
"""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from riskdetect.adapters import load_adapter, run_adapter
from riskdetect.schema import Event, EventType, Rejection, RejectionReason
from riskdetect.synthetic import SimulationResult, write_simulation
from riskdetect.synthetic.platforms import NOISE_ACTION, PROFILES

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = ["synthetic_forum", "synthetic_chat", "synthetic_market"]


@pytest.fixture(scope="module")
def translated(
    tiny_result: SimulationResult, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, tuple[list[Event], list[Rejection]]]:
    root = tmp_path_factory.mktemp("sim")
    write_simulation(tiny_result, root / "data")
    out: dict[str, tuple[list[Event], list[Rejection]]] = {}
    for platform in PLATFORMS:
        adapter = load_adapter(
            platform, config_dir=PROJECT_ROOT / "configs" / "platforms", base_dir=root
        )
        results = list(run_adapter(adapter, adapter.new_report()))
        out[platform] = (
            [r for r in results if isinstance(r, Event)],
            [r for r in results if isinstance(r, Rejection)],
        )
    return out


def noise_count(result: SimulationResult, platform: str) -> int:
    action_column = {
        "synthetic_forum": "kind",
        "synthetic_chat": "event",
        "synthetic_market": "action",
    }
    return sum(1 for row in result.rows[platform] if row[action_column[platform]] == NOISE_ACTION)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_only_junk_rows_are_rejected(
    platform: str,
    tiny_result: SimulationResult,
    translated: dict[str, tuple[list[Event], list[Rejection]]],
) -> None:
    events, rejections = translated[platform]
    assert {r.reason for r in rejections} <= {RejectionReason.UNMAPPED_ACTION}
    assert len(rejections) == noise_count(tiny_result, platform)
    assert len(events) + len(rejections) == len(tiny_result.rows[platform])


@pytest.mark.parametrize("platform", PLATFORMS)
def test_event_ids_are_unique(
    platform: str, translated: dict[str, tuple[list[Event], list[Rejection]]]
) -> None:
    events, _ = translated[platform]
    assert len({e.event_id for e in events}) == len(events)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_actor_is_in_the_answer_key(
    platform: str,
    tiny_result: SimulationResult,
    translated: dict[str, tuple[list[Event], list[Rejection]]],
) -> None:
    events, _ = translated[platform]
    known = {e.label.actor_id for e in tiny_result.answer_key if e.label.platform == platform}
    assert {e.actor_id for e in events} <= known


def test_all_time_formats_land_on_the_same_utc_clock(
    tiny_result: SimulationResult, translated: dict[str, tuple[list[Event], list[Rejection]]]
) -> None:
    window_start = tiny_result.scenario.start
    window_end = tiny_result.scenario.end
    for platform in PLATFORMS:
        events, _ = translated[platform]
        activity = [e.occurred_at for e in events if e.event_type is not EventType.ACCOUNT_CREATED]
        assert all(t.tzinfo == UTC for t in activity)
        # ISO-Z, epoch-ms and local-India inputs must all fall inside the simulated window.
        assert min(activity) >= window_start
        assert max(activity) < window_end


def test_replies_keep_their_parent(
    translated: dict[str, tuple[list[Event], list[Rejection]]],
) -> None:
    events, _ = translated["synthetic_forum"]
    replies = [e for e in events if e.content is not None and e.content.kind == "reply"]
    assert replies
    assert all(r.target is not None and r.target.owner_actor_id for r in replies)


def test_mix_of_native_and_derived_ids(
    translated: dict[str, tuple[list[Event], list[Rejection]]],
) -> None:
    events, _ = translated["synthetic_chat"]
    kinds = Counter(":d:" in e.event_id for e in events)
    assert kinds[True] > 0  # reactions and joins have no ID in the export
    assert kinds[False] > 0  # messages do


def test_no_raw_text_survives(
    tiny_result: SimulationResult, translated: dict[str, tuple[list[Event], list[Rejection]]]
) -> None:
    sample_text = next(r["body"] for r in tiny_result.rows["synthetic_forum"] if r["body"])
    for platform in PLATFORMS:
        events, rejections = translated[platform]
        for event in events[:2000]:
            assert sample_text not in event.model_dump_json()
        for rejection in rejections:
            assert rejection.raw is not None
            assert PROFILES[platform].columns[5] not in rejection.raw  # the text column
    assert datetime.now(UTC) > tiny_result.scenario.end
