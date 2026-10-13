import json
from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise
from statistics import median
from typing import Any

from riskdetect.synthetic import PersonaName, Scenario, SimulationResult, simulate
from riskdetect.synthetic.generator import AnswerKeyEntry
from riskdetect.synthetic.platforms import NOISE_ACTION

BAD = {PersonaName.SPAM_BOT, PersonaName.SLOW_SPAMMER, PersonaName.HIJACKED}


def forum_rows(result: SimulationResult) -> list[dict[str, Any]]:
    return result.rows["synthetic_forum"]


def forum_key(result: SimulationResult) -> dict[str, AnswerKeyEntry]:
    return {e.label.actor_id: e for e in result.answer_key if e.label.platform == "synthetic_forum"}


def ts(row: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(row["ts"])


def content_rows_by_actor(result: SimulationResult) -> dict[str, list[dict[str, Any]]]:
    by_actor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in forum_rows(result):
        if row["kind"] in ("submission", "comment"):
            by_actor[row["author"]].append(row)
    return by_actor


class TestDeterminism:
    def test_same_seed_same_data(
        self, tiny_scenario: Scenario, tiny_result: SimulationResult
    ) -> None:
        again = simulate(tiny_scenario)
        assert again.rows == tiny_result.rows
        assert again.answer_key == tiny_result.answer_key

    def test_different_seed_different_data(
        self, tiny_scenario: Scenario, tiny_result: SimulationResult
    ) -> None:
        other = simulate(tiny_scenario.model_copy(update={"seed": 8}))
        assert other.rows != tiny_result.rows


class TestAnswerKey:
    def test_one_entry_per_user(
        self, tiny_scenario: Scenario, tiny_result: SimulationResult
    ) -> None:
        for platform, users in tiny_scenario.platforms.items():
            entries = [e for e in tiny_result.answer_key if e.label.platform == platform]
            assert len(entries) == users
            assert len({e.label.actor_id for e in entries}) == users

    def test_abuse_start_only_for_bad_and_inside_window(
        self, tiny_scenario: Scenario, tiny_result: SimulationResult
    ) -> None:
        for entry in tiny_result.answer_key:
            start = entry.label.abuse_start
            if entry.persona in BAD:
                assert start is not None
                assert tiny_scenario.start <= start < tiny_scenario.end
            else:
                assert start is None

    def test_raw_data_does_not_reveal_personas(self, tiny_result: SimulationResult) -> None:
        dumped = json.dumps(tiny_result.rows, default=str)
        for persona in PersonaName:
            assert persona.value not in dumped


class TestRows:
    def test_rows_are_in_time_order(self, tiny_result: SimulationResult) -> None:
        times = [ts(row) for row in forum_rows(tiny_result)]
        assert times == sorted(times)

    def test_replies_and_votes_point_at_earlier_content(
        self, tiny_result: SimulationResult
    ) -> None:
        seen: set[str] = set()
        for row in forum_rows(tiny_result):
            if row["kind"] in ("comment", "upvote", "downvote", "save", "report"):
                assert row["parent_id"] in seen
            # Junk rows still stand for real content; only their action name is scrambled.
            if row["kind"] in ("submission", "comment", NOISE_ACTION):
                seen.add(row["id"])

    def test_noise_rows_exist_at_about_the_configured_rate(
        self, tiny_result: SimulationResult
    ) -> None:
        rows = forum_rows(tiny_result)
        noise = sum(1 for row in rows if row["kind"] == NOISE_ACTION)
        assert 0 < noise < 0.03 * len(rows)

    def test_every_user_signs_up_once(self, tiny_result: SimulationResult) -> None:
        signups = [row["author"] for row in forum_rows(tiny_result) if row["kind"] == "signup"]
        assert len(signups) == len(set(signups))


class TestPersonaBehavior:
    def test_spam_bots_post_links_in_regular_bursts_at_any_hour(
        self, tiny_result: SimulationResult
    ) -> None:
        key = forum_key(tiny_result)
        bots = [a for a, e in key.items() if e.persona is PersonaName.SPAM_BOT]
        by_actor = content_rows_by_actor(tiny_result)
        hours: set[int] = set()
        for bot in bots:
            abuse_start = key[bot].label.abuse_start
            assert abuse_start is not None
            # Before abuse_start a bot may warm up like a normal user; check the spam phase.
            posts = [row for row in by_actor[bot] if ts(row) >= abuse_start]
            assert posts, "every spam bot should post"
            assert all("/" in row["body"] for row in posts)  # always a link
            gaps = [(ts(b) - ts(a)).total_seconds() for a, b in pairwise(posts)]
            assert median(gaps) < 60  # bursts at machine-like speed
            hours.update(ts(row).hour for row in posts)
        assert len(hours) >= 12  # bots do not sleep

    def test_hijacked_accounts_change_behavior_at_takeover(
        self, tiny_result: SimulationResult
    ) -> None:
        key = forum_key(tiny_result)
        by_actor = content_rows_by_actor(tiny_result)
        for actor, entry in key.items():
            if entry.persona is not PersonaName.HIJACKED:
                continue
            takeover = entry.label.abuse_start
            assert takeover is not None
            after = [r for r in by_actor[actor] if ts(r) >= takeover]
            assert after and all(("/" in r["body"]) for r in after)
            texts_after = [r["body"] for r in after]
            assert len(set(texts_after)) < len(texts_after)  # repeats itself

    def test_enthusiastic_new_users_are_new_active_and_varied(
        self, tiny_scenario: Scenario, tiny_result: SimulationResult
    ) -> None:
        key = forum_key(tiny_result)
        by_actor = content_rows_by_actor(tiny_result)
        signup = {r["author"]: ts(r) for r in forum_rows(tiny_result) if r["kind"] == "signup"}
        for actor, entry in key.items():
            if entry.persona is not PersonaName.ENTHUSIASTIC_NEW:
                continue
            assert signup[actor] >= tiny_scenario.start  # joined during the window
            texts = [r["body"] for r in by_actor[actor]]
            assert len(set(texts)) == len(texts)  # never repeats itself

    def test_established_accounts_signed_up_before_the_window(
        self, tiny_scenario: Scenario, tiny_result: SimulationResult
    ) -> None:
        key = forum_key(tiny_result)
        for row in forum_rows(tiny_result):
            if row["kind"] == "signup" and key[row["author"]].persona in (
                PersonaName.NORMAL,
                PersonaName.POWER_USER,
                PersonaName.HIJACKED,
            ):
                assert ts(row) < tiny_scenario.start

    def test_market_times_are_local_india_time_without_zone(
        self, tiny_result: SimulationResult
    ) -> None:
        row = tiny_result.rows["synthetic_market"][0]
        parsed = datetime.fromisoformat(row["created_time"])
        assert parsed.tzinfo is None
        assert parsed < datetime(2027, 1, 1)
        assert isinstance(tiny_result.rows["synthetic_chat"][0]["time_ms"], int)
        assert forum_rows(tiny_result)[0]["ts"].endswith("Z")
        assert datetime.fromisoformat(forum_rows(tiny_result)[0]["ts"]).tzinfo == UTC
