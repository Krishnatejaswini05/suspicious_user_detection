"""What the whole platform has done so far: the memory behind coordination features.

Per-user summaries (state.py) cannot see that fifteen accounts push the same new site,
or that twenty brand-new accounts flooded one channel within the hour. This keeps a
small, platform-wide memory, built from past events only, in the order they are applied:

- for each website: which accounts linked it, when each first did, and when it was
  linked in the last week (a ring keeps pushing its site; a viral site is shared once);
- for each long message: which accounts posted it in the last day;
- for each space (channel, subreddit): who posted there in the last two hours.

Only fingerprints are kept, never text. Old entries are dropped as time moves on.

The memory must first watch a platform for a while: on the first day of data, every
site looks newly linked and every account looks brand new (real data: Reddit from
1 November 2008). Until enough has been seen, the answers are unknown (None).
"""

from bisect import bisect_left, insort
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from riskdetect.schema import Event, EventType

# Messages shorter than this are left out: "thanks!" or "Is this still available?" are
# typed identically by many honest people.
MIN_COPY_LENGTH = 40
_TEXT_MEMORY = timedelta(days=1)
_SPACE_MEMORY = timedelta(hours=2)
_LINK_MEMORY = timedelta(days=8)
NEWCOMER_AGE = timedelta(days=1)  # "brand new" in a space: first activity within a day
SITE_HISTORY_NEEDED = timedelta(days=14)  # to tell a new site from a long-known one
NEWCOMER_HISTORY_NEEDED = timedelta(days=7)  # to tell a newcomer from a regular

FirstActive = Callable[[str], datetime | None]


@dataclass
class CrowdState:
    first_active: FirstActive  # an actor's first activity on the platform, if known
    site_first_link: dict[str, dict[str, datetime]] = field(default_factory=dict)
    site_first_times: dict[str, list[datetime]] = field(default_factory=dict)  # sorted
    site_link_times: dict[str, list[datetime]] = field(default_factory=dict)  # sorted, recent
    text_posts: dict[str, deque[tuple[datetime, str]]] = field(default_factory=dict)
    actor_texts: dict[str, deque[tuple[datetime, str]]] = field(default_factory=dict)
    space_posts: dict[str, deque[tuple[datetime, str]]] = field(default_factory=dict)
    _text_expiry: deque[tuple[datetime, str]] = field(default_factory=deque)
    _space_expiry: deque[tuple[datetime, str]] = field(default_factory=deque)
    _link_expiry: deque[tuple[datetime, str]] = field(default_factory=deque)
    _newest: datetime | None = None
    _oldest: datetime | None = None

    def apply(self, event: Event) -> None:
        if event.event_type is not EventType.CONTENT_CREATED or event.content is None:
            return
        moment, actor, content = event.occurred_at, event.actor_id, event.content
        self._newest = moment if self._newest is None else max(self._newest, moment)
        self._oldest = moment if self._oldest is None else min(self._oldest, moment)
        for domain in content.url_domains:
            linkers = self.site_first_link.setdefault(domain, {})
            times = self.site_first_times.setdefault(domain, [])
            previous = linkers.get(actor)
            if previous is None or moment < previous:
                if previous is not None:  # a late event moved this account's first link earlier
                    del times[bisect_left(times, previous)]
                linkers[actor] = moment
                insort(times, moment)
            insort(self.site_link_times.setdefault(domain, []), moment)
            self._link_expiry.append((moment, domain))
        if (
            content.text_hash is not None
            and content.length is not None
            and content.length >= MIN_COPY_LENGTH
        ):
            self.text_posts.setdefault(content.text_hash, deque()).append((moment, actor))
            self.actor_texts.setdefault(actor, deque()).append((moment, content.text_hash))
            self._text_expiry.append((moment, content.text_hash))
        if event.space_id is not None:
            self.space_posts.setdefault(event.space_id, deque()).append((moment, actor))
            self._space_expiry.append((moment, event.space_id))
        self._prune()

    # -- questions -----------------------------------------------------------------

    def has_watched(self, as_of: datetime, needed: timedelta) -> bool:
        """Has the platform been watched for at least ``needed`` before ``as_of``?"""
        return self._oldest is not None and as_of - self._oldest >= needed

    def site_linkers(self, domain: str, as_of: datetime, window: timedelta) -> tuple[int, int]:
        """(accounts first linking ``domain`` in ``window`` before ``as_of``, all before it)."""
        times = self.site_first_times.get(domain, [])
        before = bisect_left(times, as_of)
        return before - bisect_left(times, as_of - window), before

    def site_links(self, domain: str, as_of: datetime, window: timedelta) -> int:
        """How often ``domain`` was linked (by anyone) within ``window`` before ``as_of``."""
        times = self.site_link_times.get(domain, [])
        return bisect_left(times, as_of) - bisect_left(times, as_of - window)

    def copied_by_others(self, actor: str, as_of: datetime, window: timedelta) -> int:
        """Most other accounts that posted one of ``actor``'s recent long messages."""
        since = as_of - window
        best = 0
        for moment, text_hash in self.actor_texts.get(actor, ()):
            if not since <= moment < as_of:
                continue
            others = {
                a
                for t, a in self.text_posts.get(text_hash, ())
                if a != actor and since <= t < as_of
            }
            best = max(best, len(others))
        return best

    def newcomers_in_space(self, space: str, as_of: datetime, window: timedelta) -> int:
        """Brand-new accounts that posted in ``space`` within ``window`` before ``as_of``."""
        posters = {a for t, a in self.space_posts.get(space, ()) if as_of - window <= t < as_of}
        count = 0
        for actor in posters:
            first = self.first_active(actor)
            if first is not None and first >= as_of - window - NEWCOMER_AGE:
                count += 1
        return count

    # -- forgetting ----------------------------------------------------------------------

    def _prune(self) -> None:
        if self._newest is None:
            return
        text_cut = self._newest - _TEXT_MEMORY - timedelta(hours=1)
        while self._text_expiry and self._text_expiry[0][0] < text_cut:
            _, text_hash = self._text_expiry.popleft()
            posts = self.text_posts.get(text_hash)
            while posts and posts[0][0] < text_cut:
                _, actor = posts.popleft()
                mine = self.actor_texts.get(actor)
                while mine and mine[0][0] < text_cut:
                    mine.popleft()
                if mine is not None and not mine:
                    del self.actor_texts[actor]
            if posts is not None and not posts:
                del self.text_posts[text_hash]
        link_cut = self._newest - _LINK_MEMORY
        while self._link_expiry and self._link_expiry[0][0] < link_cut:
            _, domain = self._link_expiry.popleft()
            times = self.site_link_times.get(domain)
            if times is not None:
                del times[: bisect_left(times, link_cut)]
                if not times:
                    del self.site_link_times[domain]
        space_cut = self._newest - _SPACE_MEMORY
        while self._space_expiry and self._space_expiry[0][0] < space_cut:
            _, space = self._space_expiry.popleft()
            posts = self.space_posts.get(space)
            while posts and posts[0][0] < space_cut:
                posts.popleft()
            if posts is not None and not posts:
                del self.space_posts[space]
