"""How the users in a scenario behave: everyday habits, and the tricks of bad actors.

Each function adds one user's activity to a World between two days. Humans act in
sessions during their waking hours, with irregular gaps; automated accounts act at
any hour with steady gaps. Days are counted from the scenario's start.
"""

from datetime import datetime, timedelta

from riskdetect.scenarios.world import World, at

# -- timing ---------------------------------------------------------------------------


def human_moments(
    world: World,
    day: int,
    sessions: float,
    actions: float,
    *,
    tz_hours: float = 0.0,
    wake: float = 8.0,
) -> list[datetime]:
    """Action times for one day: a few sessions in waking hours, irregular gaps inside each."""
    rng = world.rng
    moments: list[datetime] = []
    for _ in range(_count(world, sessions)):
        moment = at(day, wake + rng.uniform(0, 15) - tz_hours)
        for _ in range(1 + _count(world, max(actions - 1, 0))):
            moments.append(moment)
            moment += timedelta(seconds=max(5.0, rng.expovariate(1 / 120)))
    return moments


def _count(world: World, mean: float) -> int:
    """A random whole number with the given average."""
    whole = int(mean)
    return whole + (1 if world.rng.random() < mean - whole else 0)


# -- everyday people ----------------------------------------------------------------------


def ordinary(
    world: World,
    actor: str,
    first_day: int,
    last_day: int,
    *,
    sessions: float = 1.2,
    actions: float = 4.0,
    write_share: float = 0.45,
    reply_share: float = 0.6,
    link_rate: float = 0.08,
    sites: tuple[str, ...] | None = None,
    tz_hours: float = 0.0,
    boost: dict[int, float] | None = None,
) -> None:
    """A regular person: reads, votes, writes now and then, sometimes shares a link."""
    rng = world.rng
    for day in range(first_day, last_day):
        factor = (boost or {}).get(day, 1.0)
        for moment in human_moments(world, day, sessions * factor, actions, tz_hours=tz_hours):
            if rng.random() >= write_share:
                world.vote(actor, moment)
                continue
            text = world.chatter()
            if rng.random() < link_rate:
                text += " " + world.link(rng.choice(sites) if sites else None)
            world.write(actor, moment, text, reply=rng.random() < reply_share)


def link_spree(world: World, actor: str, day: int, posts: int) -> None:
    """One evening of sharing interesting finds: every link from a different website."""
    for i in range(posts):
        moment = at(day, 19) + timedelta(minutes=12 * i + world.rng.uniform(0, 8))
        site = f"site{world.rng.randrange(10_000)}.example"
        world.write(actor, moment, f"{world.chatter((5, 12))} {world.link(site)}")


def notice_round(world: World, actor: str, day: int, threads: int, notice: str) -> None:
    """A moderator pasting the same rules notice into many threads, one after another."""
    for i in range(threads):
        moment = at(day, 10) + timedelta(minutes=2 * i + world.rng.uniform(0, 1.5))
        world.write(actor, moment, notice, reply=True)


def answering_spree(
    world: World, actor: str, day: int, answers: int, sites: tuple[str, ...]
) -> None:
    """An expert answering a pile of questions in one sitting, citing their usual sources."""
    for i in range(answers):
        moment = at(day, 9) + timedelta(minutes=9 * i + world.rng.uniform(0, 6))
        text = f"{world.chatter((10, 30))} See {world.link(world.rng.choice(sites))}"
        world.write(actor, moment, text, reply=True)


# -- bad actors --------------------------------------------------------------------------------

_SPIN = (
    ("Earn", "Make", "Get", "Collect", "Grab"),
    ("money", "cash", "income", "profit", "dollars"),
    ("fast", "quickly", "today", "easily", "from home"),
    ("with this", "using this", "thanks to this", "through this", "via this"),
    ("trick", "method", "system", "secret", "plan"),
)


def spun_ad(world: World, site: str) -> str:
    """An ad reworded every time (word swaps plus filler), so no two copies match."""
    words = " ".join(world.rng.choice(options) for options in _SPIN)
    return f"{world.chatter((3, 8))} {words}: {world.link(site)} {world.chatter((3, 8))}"


def copy_paste_bot(world: World, actor: str, day: int, ad: str, bursts: int = 4) -> None:
    """The classic: bursts of the very same ad, seconds apart, around the clock."""
    world.signup(actor, at(day))
    for b in range(bursts):
        start = at(day, 1 + 5.5 * b)
        for i in range(15):
            world.write(actor, start + timedelta(seconds=10 * i), ad)


def disguised_bot(
    world: World, actor: str, first_day: int, last_day: int, site: str, per_day: int
) -> None:
    """A bot that tries to look human: waking hours, random gaps, reworded ads, small talk."""
    rng = world.rng
    world.signup(actor, at(first_day))
    for day in range(first_day, last_day):
        moment = at(day, 8 + rng.uniform(0, 2))
        for _ in range(per_day):
            moment += timedelta(minutes=rng.uniform(8, 60))
            roll = rng.random()
            if roll < 0.2:
                world.vote(actor, moment)
            elif roll < 0.35:
                world.write(actor, moment, world.chatter(), reply=True)  # small talk
            else:
                world.write(actor, moment, spun_ad(world, site), reply=rng.random() < 0.4)


def slow_spammer(
    world: World, actor: str, first_day: int, last_day: int, site: str, per_day: int = 2
) -> None:
    """Low and slow: a couple of reworded links a day, every day, never a burst."""
    for day in range(first_day, last_day):
        for _ in range(per_day):
            moment = at(day, world.rng.uniform(9, 21))
            world.write(actor, moment, spun_ad(world, site))


def takeover_bursts(world: World, actor: str, first_day: int, last_day: int, ad: str) -> None:
    """A stolen account used by a bot: bursts of one ad at steady intervals, at all hours."""
    for day in range(first_day, last_day):
        for b in range(3):
            start = at(day, 2 + 7 * b)
            for i in range(12):
                world.write(actor, start + timedelta(seconds=30 * i), ad, reply=i % 3 == 0)


def gradual_takeover(
    world: World, actor: str, first_day: int, days: int, site: str, start_per_day: int = 2
) -> None:
    """A stolen account eased into spam: each day a little more, and more of it links."""
    for d in range(days):
        day = first_day + d
        posts = start_per_day + 2 * d
        for _ in range(posts):
            moment = at(day, world.rng.uniform(8, 22))
            if world.rng.random() < min(1.0, 0.3 + 0.15 * d):
                world.write(actor, moment, spun_ad(world, site))
            else:
                world.write(actor, moment, world.chatter(), reply=True)


def comment_spammer(
    world: World, actor: str, first_day: int, last_day: int, site: str, per_day: int
) -> None:
    """Never starts a thread: replies under other people's posts, each with the same site."""
    world.signup(actor, at(first_day))
    for day in range(first_day, last_day):
        for _ in range(per_day):
            moment = at(day, world.rng.uniform(7, 23))
            world.write(actor, moment, spun_ad(world, site), reply=True)


def self_promoter(
    world: World, actor: str, first_day: int, last_day: int, site: str, per_day: int
) -> None:
    """Posts only links to their own site, a different article each time, never joins in."""
    for day in range(first_day, last_day):
        for _ in range(per_day):
            moment = at(day, world.rng.uniform(8, 20))
            world.write(actor, moment, f"{world.chatter((5, 10))} {world.link(site)}")


def spam_ring(
    world: World, actors: list[str], first_day: int, last_day: int, site: str, per_day: int
) -> None:
    """Many fresh accounts, each posting a little for one site and upvoting each other."""
    rng = world.rng
    for actor in actors:
        world.signup(actor, at(first_day, rng.uniform(0, 6)))
    for day in range(first_day, last_day):
        for actor in actors:
            for _ in range(per_day):
                moment = at(day, rng.uniform(8, 22))
                world.write(actor, moment, spun_ad(world, site))
                for _ in range(2):
                    friend = rng.choice(actors)
                    mine = world.content_by(friend)
                    if friend != actor and mine:
                        world.vote(actor, moment + timedelta(minutes=1), mine[-1])


def reported_poster(world: World, actor: str, first_day: int, last_day: int, site: str) -> None:
    """Posts promotions that people keep reporting and nobody answers."""
    world.signup(actor, at(first_day))
    reporters = [f"bystander{i}" for i in range(12)]
    for day in range(first_day, last_day):
        for _ in range(4):
            moment = at(day, world.rng.uniform(8, 20))
            item = (world.write(actor, moment, spun_ad(world, site)), actor)
            for reporter in world.rng.sample(reporters, 3):
                world.report(reporter, moment + timedelta(minutes=world.rng.uniform(2, 90)), item)


def controversial_poster(
    world: World, actor: str, first_day: int, last_day: int, crowd: list[str]
) -> None:
    """Strong opinions: often reported, but also widely answered - a debate, not spam."""
    rng = world.rng
    for day in range(first_day, last_day):
        for _ in range(3):
            moment = at(day, rng.uniform(9, 21))
            item = (world.write(actor, moment, world.chatter((20, 40))), actor)
            for person in rng.sample(crowd, 5):
                world.write(
                    person,
                    moment + timedelta(minutes=rng.uniform(1, 120)),
                    world.chatter(),
                    reply=True,
                    to=item,
                )
            for person in rng.sample(crowd, 2):
                world.report(person, moment + timedelta(minutes=rng.uniform(5, 60)), item)
