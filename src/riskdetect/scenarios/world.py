"""A small simulated world for one scenario: events built exactly as an adapter would.

Text is fingerprinted (hash, simhash, link domains) with the same functions the
adapters use, then discarded, so the detector sees scenario events exactly as it
sees real ones. Every world is seeded: the same scenario always gives the same events.
"""

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from riskdetect.adapters.transforms import (
    extract_domains,
    hash_text,
    mentions_offsite_contact,
    mentions_risky_payment,
    simhash_text,
)
from riskdetect.schema import Event

PLATFORM = "scenario"
START = datetime(2026, 3, 1, tzinfo=UTC)
DAYS = 28
ACTION_DAY = 21  # history before this day; the situation under test starts on it
SPACES = tuple(f"s/{name}" for name in "news tech music food sport travel games help".split())

_WORDS = (
    "the a this that it is was are have had do not just really very so also today week "
    "time day night people friend team family work home city game music movie book food "
    "coffee weather trip photo idea question answer problem help thanks great good nice "
    "new old first best think know feel want need like love try make take give find tell "
    "ask see look read write play learn build fix use start open buy price quality phone "
    "laptop bike car garden kitchen recipe dinner school class project code bug release "
    "update news story event match season player goal win anyone everyone maybe always "
    "never sometimes again still already almost enough about after before during while"
).split()
_EVERYDAY_SITES = (
    "wikipedia.org",
    "youtube.com",
    "github.com",
    "bbc.co.uk",
    "nytimes.com",
    "imgur.com",
    "stackoverflow.com",
    "reuters.com",
    "theguardian.com",
    "nature.com",
)


def at(day: float, hour: float = 0.0) -> datetime:
    """A moment in the scenario: ``day`` days (and ``hour`` hours) after its start."""
    return START + timedelta(days=day, hours=hour)


@dataclass
class World:
    seed: int
    rng: random.Random = field(init=False)
    events: list[Event] = field(default_factory=list)
    _content: list[tuple[str, str]] = field(default_factory=list)  # (content id, owner)
    _counter: int = 0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    # -- text ---------------------------------------------------------------------

    def chatter(self, words: tuple[int, int] = (6, 24)) -> str:
        """Ordinary varied text: no two pieces alike."""
        count = self.rng.randint(*words)
        return " ".join(self.rng.choices(_WORDS, k=count)).capitalize() + "."

    def link(self, site: str | None = None) -> str:
        site = site or self.rng.choice(_EVERYDAY_SITES)
        path = "".join(self.rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
        return f"https://{site}/{path}"

    # -- events -------------------------------------------------------------------

    def _id(self, kind: str) -> str:
        self._counter += 1
        return f"{PLATFORM}:{kind}{self._counter}"

    def signup(self, actor: str, when: datetime) -> None:
        self.events.append(
            Event(
                event_id=self._id("signup"),
                platform=PLATFORM,
                actor_id=actor,
                event_type="ACCOUNT_CREATED",
                occurred_at=when,
            )
        )

    def write(
        self,
        actor: str,
        when: datetime,
        text: str,
        *,
        reply: bool = False,
        space: str | None = None,
        to: tuple[str, str] | None = None,
        price: float | None = None,
    ) -> str:
        """A post (or a reply to someone else's content). Returns the new content's id.

        A post with a ``price`` is a marketplace listing.
        """
        content_id = self._id("c")
        target = None
        if reply:
            parent = to or self.someone_elses_content(actor)
            if parent is not None:
                target = {"type": "content", "id": parent[0], "owner_actor_id": parent[1]}
        self.events.append(
            Event(
                event_id=content_id,
                platform=PLATFORM,
                actor_id=actor,
                event_type="CONTENT_CREATED",
                occurred_at=when,
                space_id=space or self.rng.choice(SPACES),
                target=target,
                content={
                    "kind": "reply" if target is not None else "post",
                    "text_hash": hash_text(text),
                    "simhash": simhash_text(text),
                    "length": len(text),
                    "url_domains": extract_domains(text),
                    "offsite_contact": mentions_offsite_contact(text),
                    "risky_payment": mentions_risky_payment(text),
                    "price": price,
                },
            )
        )
        self._content.append((content_id, actor))
        return content_id

    def vote(self, actor: str, when: datetime, to: tuple[str, str] | None = None) -> None:
        parent = to or self.someone_elses_content(actor)
        if parent is None:
            return
        self.events.append(
            Event(
                event_id=self._id("v"),
                platform=PLATFORM,
                actor_id=actor,
                event_type="INTERACTION",
                occurred_at=when,
                target={"type": "content", "id": parent[0], "owner_actor_id": parent[1]},
                interaction={"kind": "vote_up"},
            )
        )

    def report(self, actor: str, when: datetime, to: tuple[str, str]) -> None:
        self.events.append(
            Event(
                event_id=self._id("r"),
                platform=PLATFORM,
                actor_id=actor,
                event_type="REPORT_FILED",
                occurred_at=when,
                target={"type": "content", "id": to[0], "owner_actor_id": to[1]},
            )
        )

    # -- what exists ------------------------------------------------------------------

    def someone_elses_content(self, actor: str) -> tuple[str, str] | None:
        recent = self._content[-300:]
        for _ in range(8):
            if not recent:
                return None
            item = self.rng.choice(recent)
            if item[1] != actor:
                return item
        return None

    def content_by(self, actor: str) -> list[tuple[str, str]]:
        return [item for item in self._content if item[1] == actor]

    def sorted_events(self) -> list[Event]:
        return sorted(self.events, key=lambda e: (e.occurred_at, e.event_id))
