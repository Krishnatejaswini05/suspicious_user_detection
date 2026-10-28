"""The scenario library: situations the detector must handle, each with the expected outcome.

Two kinds:
- innocent: unusual but honest behavior that must never reach REVIEW;
- abuse: bad behavior that must reach REVIEW within a stated time.

``known_gap`` marks a situation the detector is known not to handle yet, with the
reason. Those are reported as gaps instead of failures, and the test suite notices
when one starts passing, so the mark can be removed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from riskdetect.scenarios import behaviours as b
from riskdetect.scenarios.world import ACTION_DAY, DAYS, World, at

DOCS = ("docs.python.org", "developer.mozilla.org", "wikipedia.org")
CROWD = [f"crowd{i}" for i in range(25)]


@dataclass(frozen=True)
class Expect:
    """What must happen to some users.

    caught=True: at least ``share`` of ``actors`` reach REVIEW (or HIGH) within ``within``
    of ``start``. caught=False: none of them reach REVIEW between ``start`` and ``until``.
    """

    actors: tuple[str, ...]
    caught: bool
    start: datetime
    within: timedelta | None = None
    until: datetime | None = None
    share: float = 1.0

    def describe(self) -> str:
        who = self.actors[0] if len(self.actors) == 1 else f"{len(self.actors)} users"
        if not self.caught:
            when = f" before day {(self.until - at(0)).days}" if self.until else ""
            return f"{who}: never REVIEW or HIGH{when}"
        hours = (self.within or timedelta(0)).total_seconds() / 3600
        span = f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.0f} days"
        part = "" if self.share == 1 else f"{self.share:.0%} of "
        return f"{part}{who}: REVIEW or HIGH within {span}"


def unflagged(*actors: str, until: datetime | None = None) -> Expect:
    return Expect(tuple(actors), caught=False, start=at(0), until=until)


def caught(hours: float, *actors: str, start: datetime | None = None, share: float = 1.0) -> Expect:
    """Caught within ``hours`` of each user's first action from ``start`` (default: day 21)."""
    return Expect(
        tuple(actors),
        caught=True,
        start=start or at(ACTION_DAY),
        within=timedelta(hours=hours),
        share=share,
    )


@dataclass(frozen=True)
class Scenario:
    name: str
    kind: str  # "innocent" or "abuse"
    story: str
    build: Callable[[World], list[Expect]]
    known_gap: str | None = None
    allowlist: tuple[str, ...] = ()  # accounts the platform has marked as trusted (staff)


def crowd(world: World) -> None:
    """The everyday members present in every scenario (content to reply to, a public)."""
    for i, actor in enumerate(CROWD):
        world.signup(actor, at(-400 + 10 * i))
        b.ordinary(world, actor, 0, DAYS, sessions=0.8 + (i % 5) * 0.4)


def member(world: World, actor: str, until: int = ACTION_DAY, **habits: object) -> None:
    """An established member with ordinary history up to ``until``."""
    world.signup(actor, at(-300))
    b.ordinary(world, actor, 0, until, **habits)  # type: ignore[arg-type]


# -- innocent ------------------------------------------------------------------------------


def _everyday(world: World) -> list[Expect]:
    return [unflagged(*CROWD)]


def _news_day(world: World) -> list[Expect]:
    people = [f"reader{i}" for i in range(12)]
    for actor in people:
        member(world, actor, until=DAYS, boost={ACTION_DAY: 5.0})
    return [unflagged(*people)]


def _holiday(world: World) -> list[Expect]:
    member(world, "holidayer", until=DAYS, boost={ACTION_DAY: 8.0, ACTION_DAY + 1: 8.0})
    return [unflagged("holidayer")]


def _power_user(world: World) -> list[Expect]:
    member(world, "poweruser", until=DAYS, sessions=6, actions=8, link_rate=0.15)
    return [unflagged("poweruser")]


def _link_sharer(world: World) -> list[Expect]:
    member(world, "sharer", until=DAYS, link_rate=0.2)
    b.link_spree(world, "sharer", ACTION_DAY, posts=14)
    return [unflagged("sharer")]


def _expert(world: World) -> list[Expect]:
    member(world, "expert", until=DAYS, link_rate=0.8, sites=DOCS, reply_share=0.9)
    b.answering_spree(world, "expert", ACTION_DAY, answers=20, sites=DOCS)
    return [unflagged("expert")]


def _allowlisted_moderator(world: World) -> list[Expect]:
    return _moderator(world)


def _moderator(world: World) -> list[Expect]:
    notice = (
        "Reminder: please read the community rules before posting. Thanks for keeping it friendly."
    )
    member(world, "moderator", until=DAYS)
    for day in (7, 14, ACTION_DAY):
        b.notice_round(world, "moderator", day, threads=12, notice=notice)
    return [unflagged("moderator")]


def _traveller(world: World) -> list[Expect]:
    member(world, "traveller")
    b.ordinary(world, "traveller", ACTION_DAY, DAYS, tz_hours=9)
    return [unflagged("traveller")]


def _newcomer(world: World) -> list[Expect]:
    world.signup("newcomer", at(ACTION_DAY))
    b.ordinary(world, "newcomer", ACTION_DAY, DAYS, sessions=4, actions=6, link_rate=0.12)
    return [unflagged("newcomer")]


def _returning(world: World) -> list[Expect]:
    member(world, "returner", until=4)
    b.ordinary(world, "returner", ACTION_DAY + 1, DAYS, sessions=3, actions=6, link_rate=0.15)
    return [unflagged("returner")]


def _controversial(world: World) -> list[Expect]:
    member(world, "debater")
    b.controversial_poster(world, "debater", ACTION_DAY, DAYS, CROWD)
    return [unflagged("debater")]


# -- abuse ------------------------------------------------------------------------------------


def _copy_paste(world: World) -> list[Expect]:
    b.copy_paste_bot(world, "adbot", ACTION_DAY, "Cheap phones today only! visit bit.ly/ph0n3s")
    return [caught(1, "adbot")]


def _scam_site(world: World) -> list[Expect]:
    world.signup("scammer", at(ACTION_DAY))
    b.ordinary(world, "scammer", ACTION_DAY, ACTION_DAY + 1, sessions=1, actions=3)
    world.write("scammer", at(ACTION_DAY, 15), "Double your coins here https://coin-profit.xyz/x1")
    return [caught(1, "scammer", start=at(ACTION_DAY, 15))]


def _sudden_takeover(world: World) -> list[Expect]:
    member(world, "victim")
    b.takeover_bursts(
        world, "victim", ACTION_DAY, ACTION_DAY + 3, "Best deals " + world.link("deals-now.shop")
    )
    return [unflagged("victim", until=at(ACTION_DAY)), caught(6, "victim")]


def _gradual_takeover(world: World) -> list[Expect]:
    member(world, "slowvictim")
    b.gradual_takeover(world, "slowvictim", ACTION_DAY, 7, "quiet-offers.shop")
    return [unflagged("slowvictim", until=at(ACTION_DAY)), caught(24 * 7, "slowvictim")]


def _disguised_bot(world: World) -> list[Expect]:
    b.disguised_bot(world, "humanlike", ACTION_DAY, DAYS, "easy-income.biz", per_day=25)
    return [caught(48, "humanlike")]


def _slow_spammer(world: World) -> list[Expect]:
    world.signup("slowspam", at(ACTION_DAY - 7))
    b.ordinary(world, "slowspam", ACTION_DAY - 7, ACTION_DAY, sessions=0.5, actions=2)
    b.slow_spammer(world, "slowspam", ACTION_DAY, DAYS, "pills-direct.store", per_day=2)
    return [caught(24 * 7, "slowspam")]


def _self_promoter(world: World) -> list[Expect]:
    world.signup("promoter", at(-100))
    b.self_promoter(world, "promoter", ACTION_DAY, DAYS, "my-blog-network.net", per_day=4)
    return [caught(24 * 4, "promoter")]


def _comment_spammer(world: World) -> list[Expect]:
    b.comment_spammer(world, "replyspam", ACTION_DAY, DAYS, "cheap-followers.top", per_day=15)
    return [caught(24, "replyspam")]


def _shortener(world: World) -> list[Expect]:
    world.signup("shortlinks", at(ACTION_DAY))
    for day in range(ACTION_DAY, DAYS):
        for _ in range(8):
            moment = at(day, world.rng.uniform(8, 22))
            code = "".join(world.rng.choices("abcdefghjkmnpqrstuvwxyz23456789", k=6))
            world.write("shortlinks", moment, f"{world.chatter((4, 10))} bit.ly/{code}")
    return [caught(48, "shortlinks")]


def _spam_ring(world: World) -> list[Expect]:
    ring = [f"ring{i}" for i in range(15)]
    b.spam_ring(world, ring, ACTION_DAY, DAYS, "crypto-signals.vip", per_day=3)
    return [caught(72, *ring, share=0.8)]


def _reported(world: World) -> list[Expect]:
    b.reported_poster(world, "reported", ACTION_DAY, DAYS, "miracle-diet.shop")
    return [caught(48, "reported")]


SCENARIOS: list[Scenario] = [
    # innocent
    Scenario("everyday_crowd", "innocent", "Ordinary members going about their days.", _everyday),
    Scenario(
        "news_day",
        "innocent",
        "Big news: a dozen regulars post five times as much as usual for a day.",
        _news_day,
    ),
    Scenario(
        "holiday_binge",
        "innocent",
        "One member spends a long weekend posting eight times as much.",
        _holiday,
    ),
    Scenario(
        "power_user", "innocent", "A very active member, every single day, for weeks.", _power_user
    ),
    Scenario(
        "link_sharer",
        "innocent",
        "An evening of sharing 14 finds, each from a different website.",
        _link_sharer,
    ),
    Scenario(
        "expert_linker",
        "innocent",
        "An expert who always cites sources answers 20 questions in a row.",
        _expert,
    ),
    Scenario(
        "moderator_notices",
        "innocent",
        "A moderator pastes the same rules notice into 12 threads, weekly (not on the allowlist).",
        _moderator,
        known_gap="Identical notices pasted minutes apart look exactly like a copy-paste flood. "
        "Behavior alone cannot tell them apart; platforms should allowlist their staff.",
    ),
    Scenario(
        "allowlisted_moderator",
        "innocent",
        "The same moderator, on the platform's allowlist of staff accounts.",
        _allowlisted_moderator,
        allowlist=("moderator",),
    ),
    Scenario(
        "traveller",
        "innocent",
        "A member travels and starts posting nine time zones away.",
        _traveller,
    ),
    Scenario(
        "keen_newcomer",
        "innocent",
        "A brand-new member who is very active from day one.",
        _newcomer,
    ),
    Scenario(
        "returning_member",
        "innocent",
        "A member back after three quiet weeks, catching up busily.",
        _returning,
    ),
    Scenario(
        "controversial_member",
        "innocent",
        "Strong opinions: often reported, but widely answered.",
        _controversial,
    ),
    # abuse
    Scenario(
        "copy_paste_bot",
        "abuse",
        "A new account posts the same ad in bursts, seconds apart.",
        _copy_paste,
    ),
    Scenario(
        "scam_site", "abuse", "A new account posts one link to a known scam site.", _scam_site
    ),
    Scenario(
        "sudden_takeover",
        "abuse",
        "A long-standing account is stolen and blasts ads around the clock.",
        _sudden_takeover,
    ),
    Scenario(
        "gradual_takeover",
        "abuse",
        "A stolen account eased into spam, a little more each day.",
        _gradual_takeover,
        known_gap="R004 and the self-baseline model look for a sudden jump (about 5x the usual "
        "activity). A rule without the jump (links up sharply, mostly to one site new this "
        "week) caught this case, but on real data it also flagged a trusted Stack Exchange "
        "expert and about 25 ordinary Reddit users, who had simply started linking GitHub or "
        "YouTube. Telling a thief's site apart needs to know that nobody else links it "
        "(platform-wide, with Milestone 12).",
    ),
    Scenario(
        "disguised_bot",
        "abuse",
        "A bot acting human: waking hours, random gaps, reworded ads, small talk.",
        _disguised_bot,
        known_gap="Reworded ads defeat copy detection, and the small talk and replies keep it "
        "under R009's thresholds (90% links, at most 10% replies).",
    ),
    Scenario(
        "slow_spammer",
        "abuse",
        "Two reworded spam links a day, every day, never a burst.",
        _slow_spammer,
    ),
    Scenario(
        "self_promoter",
        "abuse",
        "Only links to their own site, a new article each time, never joins in.",
        _self_promoter,
    ),
    Scenario(
        "comment_spammer",
        "abuse",
        "Never starts a thread: replies under others' posts with the same site.",
        _comment_spammer,
    ),
    Scenario(
        "shortener_spammer",
        "abuse",
        "Every post hides its destination behind a bit.ly link.",
        _shortener,
    ),
    Scenario(
        "spam_ring",
        "abuse",
        "Fifteen fresh accounts each post a little for one site and upvote each other.",
        _spam_ring,
        known_gap="Each account alone is small, so only about half are caught in time. Catching "
        "the ring needs linking accounts that push the same site (coordination, Milestone 12).",
    ),
    Scenario(
        "reported_spammer",
        "abuse",
        "Promotions that people keep reporting and nobody answers.",
        _reported,
    ),
]
