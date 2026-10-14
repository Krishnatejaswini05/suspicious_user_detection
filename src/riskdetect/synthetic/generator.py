"""Run a simulation: create users, plan their actions, and resolve who they interact with.

Two passes:
1. **Plan** - each user independently decides *when* they act and *what kind* of
   action it is (post, vote, report...), following their persona.
2. **Resolve** - all plans are merged in time order, and each reply, vote or report
   is pointed at content that already exists at that moment.

Everything is driven by seeded random generators, so a scenario always produces
exactly the same output. Each user has their own generator, so changing one
user's behavior does not reshuffle everyone else's.
"""

import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from riskdetect.schema import Label, LabelSource
from riskdetect.synthetic.actions import CREATES_CONTENT, TARGETS_CONTENT
from riskdetect.synthetic.actions import SynthAction as A
from riskdetect.synthetic.content import CAMPAIGNS, Campaign, normal_text, spam_link, spam_text
from riskdetect.synthetic.personas import PERSONAS, PersonaName, PersonaSpec
from riskdetect.synthetic.platforms import PROFILES, PlatformProfile, ResolvedAction
from riskdetect.synthetic.scenario import Scenario
from riskdetect.synthetic.timing import bot_day, human_day

_RECENT_CONTENT = 300  # replies and votes pick from this many most recent items
_REPORT_SPAM_BIAS = 0.7  # reporters notice spam more often than ordinary content
_HUMANS_SKIP_SPAM = 0.9  # people rarely reply to or like spam
_PRE_ABUSE_LINK_RATE = 0.08


@dataclass(frozen=True)
class AnswerKeyEntry:
    """The truth about one simulated user. Never shown to the detector."""

    label: Label
    persona: PersonaName


@dataclass
class SimulationResult:
    scenario: Scenario
    rows: dict[str, list[dict[str, Any]]]  # platform -> raw rows, in time order
    answer_key: list[AnswerKeyEntry]

    def summary(self) -> str:
        lines = [f"Scenario: {self.scenario.name} (seed {self.scenario.seed})"]
        for platform, rows in self.rows.items():
            entries = [e for e in self.answer_key if e.label.platform == platform]
            personas = Counter(e.persona for e in entries)
            bad = sum(1 for e in entries if e.label.abuse_start is not None)
            lines.append(
                f"  {platform}: {len(rows):,} rows, {len(entries)} users ({bad} bad) - "
                + ", ".join(f"{name} {count}" for name, count in sorted(personas.items()))
            )
        return "\n".join(lines)


@dataclass
class _User:
    actor_id: str
    spec: PersonaSpec
    rng: random.Random
    created_at: datetime
    utc_offset: timedelta
    wake_hour: float
    spaces: tuple[str, ...]
    abuse_start: datetime | None
    campaign: Campaign | None
    link: str | None
    bursts_per_day: float
    interval_seconds: float


_Item = tuple[str, str, str | None, bool]  # (content_id, owner, space, is_spam)


@dataclass(frozen=True)
class _Intent:
    time: datetime
    actor_id: str
    action: A
    text: str | None = None
    space: str | None = None
    is_spam: bool = False


def assign_personas(mix: Mapping[PersonaName, float], users: int) -> list[PersonaName]:
    """Exact persona counts for ``users`` people, matching the mix as closely as possible.

    Every persona with a positive share appears at least once when there is room,
    so even small test scenarios contain each kind of user.
    """
    total = sum(mix.values())
    shares = {name: share / total for name, share in mix.items() if share > 0}
    exact = {name: share * users for name, share in shares.items()}
    counts = {name: int(value) for name, value in exact.items()}
    by_remainder = sorted(shares, key=lambda name: exact[name] - counts[name], reverse=True)
    for name in by_remainder[: users - sum(counts.values())]:
        counts[name] += 1
    if users >= len(shares):
        for name in shares:
            if counts[name] == 0:
                donor = max(counts, key=lambda n: counts[n])
                counts[donor] -= 1
                counts[name] = 1
    return [name for name in sorted(counts) for _ in range(counts[name])]


def simulate(scenario: Scenario) -> SimulationResult:
    rows: dict[str, list[dict[str, Any]]] = {}
    answer_key: list[AnswerKeyEntry] = []
    for platform, users in scenario.platforms.items():
        platform_rows, entries = _simulate_platform(scenario, PROFILES[platform], users)
        rows[platform] = platform_rows
        answer_key.extend(entries)
    return SimulationResult(scenario, rows, answer_key)


def _simulate_platform(
    scenario: Scenario, profile: PlatformProfile, n_users: int
) -> tuple[list[dict[str, Any]], list[AnswerKeyEntry]]:
    seed = f"{scenario.seed}:{profile.name}"
    rng = random.Random(seed)
    personas = assign_personas(scenario.persona_mix, n_users)
    rng.shuffle(personas)  # so user IDs say nothing about who is bad
    busy_days = set(
        rng.sample(range(scenario.duration_days), min(scenario.busy_days, scenario.duration_days))
    )

    users = [
        _make_user(scenario, profile, f"u{i + 1:05d}", PERSONAS[name], random.Random(f"{seed}:{i}"))
        for i, name in enumerate(personas)
    ]
    intents = [intent for user in users for intent in _plan(scenario, profile, user, busy_days)]
    intents.sort(key=lambda intent: (intent.time, intent.actor_id))

    resolved = _resolve(intents, random.Random(f"{seed}:resolve"), scenario.noise_rate)
    rows = [profile.format_row(profile, item) for item in resolved]
    return rows, [_answer(scenario, profile, user) for user in users]


def _make_user(
    scenario: Scenario,
    profile: PlatformProfile,
    actor_id: str,
    spec: PersonaSpec,
    rng: random.Random,
) -> _User:
    window = timedelta(days=scenario.duration_days)
    if spec.account_age_days is not None:
        created_at = scenario.start - timedelta(days=rng.uniform(*spec.account_age_days))
    else:
        created_at = scenario.start + window * rng.uniform(*spec.created_in_window)

    abuse_start: datetime | None = None
    if spec.abuse_start is not None:
        if spec.name is PersonaName.SPAM_BOT:
            abuse_start = created_at + timedelta(days=rng.uniform(*spec.abuse_start))
        else:
            abuse_start = scenario.start + window * rng.uniform(*spec.abuse_start)
        # Abuse must actually happen inside the window, or the label would be meaningless.
        abuse_start = min(abuse_start, scenario.end - timedelta(hours=6))

    campaign = rng.choice(CAMPAIGNS) if spec.is_bad else None
    n_spaces = min(rng.randint(*spec.habits.home_spaces), len(profile.spaces))
    bot = spec.bot
    return _User(
        actor_id=actor_id,
        spec=spec,
        rng=rng,
        created_at=created_at,
        utc_offset=timedelta(hours=rng.choice(profile.utc_offsets)),
        wake_hour=rng.uniform(6.5, 10.0),
        spaces=tuple(rng.sample(profile.spaces, n_spaces)),
        abuse_start=abuse_start,
        campaign=campaign,
        link=spam_link(rng, campaign) if campaign else None,
        bursts_per_day=rng.uniform(*bot.bursts_per_day) if bot else 0.0,
        interval_seconds=rng.uniform(*bot.interval_seconds) if bot else 0.0,
    )


def _plan(
    scenario: Scenario, profile: PlatformProfile, user: _User, busy_days: set[int]
) -> list[_Intent]:
    """Everything one user will do, in their own time order (targets resolved later)."""
    intents = [_Intent(user.created_at, user.actor_id, A.SIGNUP)]
    active_from = max(user.created_at, scenario.start)
    # Bots and hijacked accounts stop acting like humans once the abuse starts.
    human_until = (
        user.abuse_start if user.spec.bot is not None and user.abuse_start else scenario.end
    )
    habits = user.spec.habits

    for day in range(scenario.duration_days):
        day_start = scenario.start + timedelta(days=day)
        boost = 2.0 if day in busy_days else 1.0
        for moment in human_day(
            user.rng,
            day_start,
            user.utc_offset,
            user.wake_hour,
            habits.sessions_per_day * boost,
            habits.actions_per_session * profile.activity,
        ):
            if active_from <= moment < min(human_until, scenario.end):
                intent = _human_action(profile, user, moment)
                if intent is not None:
                    intents.append(intent)

        if user.spec.bot is not None and user.abuse_start is not None:
            for moment in bot_day(
                user.rng, day_start, user.spec.bot, user.bursts_per_day, user.interval_seconds
            ):
                if user.abuse_start <= moment < scenario.end:
                    intents.append(_bot_action(profile, user, moment))
    return intents


def _human_action(profile: PlatformProfile, user: _User, moment: datetime) -> _Intent | None:
    rng = user.rng
    actions = list(user.spec.habits.weights)
    weights = [profile.weight(a, user.spec.habits.weights[a]) for a in actions]
    if sum(weights) <= 0:
        return None
    action = rng.choices(actions, weights=weights)[0]
    if action not in CREATES_CONTENT:
        return _Intent(moment, user.actor_id, action)

    space = rng.choice(user.spaces)
    abusing = user.abuse_start is not None and moment >= user.abuse_start
    if abusing and user.campaign is not None and user.link is not None:
        text = spam_text(rng, user.campaign, user.link)
        return _Intent(moment, user.actor_id, action, text, space, is_spam=True)
    link_rate = _PRE_ABUSE_LINK_RATE if user.spec.is_bad else user.spec.habits.link_rate
    text = normal_text(rng, profile.text_style, link_rate)
    return _Intent(moment, user.actor_id, action, text, space)


def _bot_action(profile: PlatformProfile, user: _User, moment: datetime) -> _Intent:
    rng = user.rng
    assert user.spec.bot is not None and user.campaign is not None and user.link is not None
    action = A.REPLY if rng.random() < user.spec.bot.reply_share else A.POST
    text = spam_text(rng, user.campaign, user.link)
    # Bots cross-post everywhere rather than staying in a few home spaces.
    return _Intent(moment, user.actor_id, action, text, rng.choice(profile.spaces), is_spam=True)


def _resolve(intents: list[_Intent], rng: random.Random, noise_rate: float) -> list[ResolvedAction]:
    """Point replies, votes, follows and reports at things that exist at that moment."""
    content: list[_Item] = []
    spam_content: list[_Item] = []
    posters: list[str] = []
    poster_set: set[str] = set()
    out: list[ResolvedAction] = []

    for intent in intents:
        seq = len(out) + 1
        action = intent.action
        space = intent.space
        target_id: str | None = None
        target_owner: str | None = None

        if action in TARGETS_CONTENT:
            source = content
            if action is A.REPORT and spam_content and rng.random() < _REPORT_SPAM_BIAS:
                source = spam_content
            avoid_spam = not intent.is_spam and action is not A.REPORT
            picked = _pick_content(rng, source, intent.actor_id, avoid_spam=avoid_spam)
            if picked is None:
                if action is not A.REPLY:
                    continue  # nothing to vote on or report yet
                action = A.POST  # a reply with nothing to reply to becomes a new post
            else:
                target_id, target_owner, target_space, _ = picked
                if action is A.REPLY:
                    space = target_space
        elif action is A.FOLLOW:
            followed = _pick_actor(rng, posters, intent.actor_id)
            if followed is None:
                continue
            target_id = followed

        content_id: str | None = None
        if action in CREATES_CONTENT:
            content_id = f"{'t' if action is A.POST else 'c'}{seq}"
            item = (content_id, intent.actor_id, space, intent.is_spam)
            content.append(item)
            if intent.is_spam:
                spam_content.append(item)
            if intent.actor_id not in poster_set:
                poster_set.add(intent.actor_id)
                posters.append(intent.actor_id)
            if len(content) > 10 * _RECENT_CONTENT:
                del content[:-_RECENT_CONTENT]

        out.append(
            ResolvedAction(
                seq=seq,
                time=intent.time,
                actor_id=intent.actor_id,
                action=action,
                content_id=content_id,
                text=intent.text if action in CREATES_CONTENT else None,
                space=space,
                target_id=target_id,
                target_owner=target_owner,
                noise=rng.random() < noise_rate,
            )
        )
    return out


def _pick_content(
    rng: random.Random, source: list[_Item], actor_id: str, *, avoid_spam: bool = False
) -> _Item | None:
    recent = source[-_RECENT_CONTENT:]
    for _ in range(5):
        if not recent:
            return None
        item = rng.choice(recent)
        if item[1] == actor_id:
            continue
        if avoid_spam and item[3] and rng.random() < _HUMANS_SKIP_SPAM:
            continue
        return item
    return None


def _pick_actor(rng: random.Random, posters: list[str], actor_id: str) -> str | None:
    for _ in range(5):
        if not posters:
            return None
        candidate = rng.choice(posters)
        if candidate != actor_id:
            return candidate
    return None


def _answer(scenario: Scenario, profile: PlatformProfile, user: _User) -> AnswerKeyEntry:
    label = Label(
        actor_id=user.actor_id,
        platform=profile.name,
        category=user.spec.category,
        # The simulation "reveals" the truth at its end; abuse_start says when it began.
        decided_at=scenario.end,
        source=LabelSource.SYNTHETIC,
        confidence=1.0,
        abuse_start=user.abuse_start if user.spec.is_bad else None,
    )
    return AnswerKeyEntry(label, user.spec.name)
