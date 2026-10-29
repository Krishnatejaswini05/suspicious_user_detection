"""Each actor's running summary, updated one event at a time.

This is the single place where events are folded into behavior. Batch feature
computation replays stored events through it; the realtime watcher (later)
feeds live events through the same code. That is what keeps the two in agreement.

Some signals are about what *others* do to an actor (reports received, replies
received). Those are applied to the target owner's summary by the engine.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from riskdetect.adapters.transforms import hamming_distance
from riskdetect.features.crowd import CrowdState
from riskdetect.features.windows import HOUR, DailyTally, TimeSeriesCounter
from riskdetect.schema import ContentKind, Event, EventType, TargetType

URL_SHORTENERS = frozenset(
    {
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "ow.ly",
        "is.gd",
        "buff.ly",
        "rebrand.ly",
        "cutt.ly",
    }
)
# A listing below this share of its category's usual price is "far below" (an iPhone for
# $150). Honest sellers clearing out cheaply do this too, so it is never enough alone.
CHEAP_LISTING_SHARE = 0.4
# Links that invite people into another server or group (chat-app invite floods).
INVITE_DOMAINS = frozenset(
    {"discord.gg", "discordapp.com", "t.me", "telegram.me", "chat.whatsapp.com"}
)
NEAR_DUPLICATE_BITS = 3  # simhashes this close count as the same text, lightly edited
_RECENT_HASHES = 200
_RECENT_SIMHASHES = 50
_RECENT_GAPS = 50
_RECENT_SPACES = 200


@dataclass
class ActorState:
    actor_id: str
    # Known-bad domains (shared, read-only); posts linking to them are counted.
    blocked_domains: frozenset[str] = frozenset()
    # The platform-wide memory shared by every actor on the platform (coordination).
    crowd: CrowdState | None = field(default=None, repr=False, compare=False)
    created_at: datetime | None = None
    first_seen: datetime | None = None
    first_active: datetime | None = None  # first event other than signup
    last_seen: datetime | None = None
    first_content_at: datetime | None = None
    events_seen: int = 0

    activity: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)  # all but signup
    content: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    posts_written: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)  # new threads
    replies_written: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    duplicates: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    with_link: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    with_shortener: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    with_blocked_domain: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    with_invite: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    interactions: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    reports_received: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    replies_received: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    # Marketplace safety: facts the adapter read from text, and listing prices.
    text_checked: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    offsite_contact: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    risky_payment: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)
    cheap_listings: TimeSeriesCounter = field(default_factory=TimeSeriesCounter)

    domains: DailyTally = field(default_factory=DailyTally)
    spaces: DailyTally = field(default_factory=DailyTally)
    hours: DailyTally = field(default_factory=DailyTally)

    recent_hashes: deque[str] = field(default_factory=lambda: deque(maxlen=_RECENT_HASHES))
    recent_spaces: deque[tuple[datetime, str]] = field(
        default_factory=lambda: deque(maxlen=_RECENT_SPACES)
    )
    recent_simhashes: deque[int] = field(default_factory=lambda: deque(maxlen=_RECENT_SIMHASHES))
    gaps_seconds: deque[float] = field(default_factory=lambda: deque(maxlen=_RECENT_GAPS))

    # -- own actions -----------------------------------------------------------

    def apply(self, event: Event) -> None:
        moment = event.occurred_at
        self.events_seen += 1
        self.first_seen = moment if self.first_seen is None else min(self.first_seen, moment)

        if event.event_type is EventType.ACCOUNT_CREATED:
            self.created_at = moment if self.created_at is None else min(self.created_at, moment)
            return

        if self.last_seen is not None and moment >= self.last_seen:
            self.gaps_seconds.append((moment - self.last_seen).total_seconds())
        self.last_seen = moment if self.last_seen is None else max(self.last_seen, moment)
        self.first_active = moment if self.first_active is None else min(self.first_active, moment)

        self.activity.add(moment)
        self.hours.add(moment, str(moment.hour))
        if event.space_id is not None:
            self.spaces.add(moment, event.space_id)
            self.recent_spaces.append((moment, event.space_id))

        if event.event_type is EventType.CONTENT_CREATED and event.content is not None:
            self._apply_content(event, moment)
        elif event.event_type is EventType.INTERACTION:
            self.interactions.add(moment)
        self._prune(moment)

    def _apply_content(self, event: Event, moment: datetime) -> None:
        content = event.content
        assert content is not None
        self.content.add(moment)
        if content.kind is ContentKind.POST:
            self.posts_written.add(moment)
        elif content.kind is ContentKind.REPLY:
            self.replies_written.add(moment)
        if self.first_content_at is None or moment < self.first_content_at:
            self.first_content_at = moment

        if content.offsite_contact is not None or content.risky_payment is not None:
            self.text_checked.add(moment)
            if content.offsite_contact:
                self.offsite_contact.add(moment)
            if content.risky_payment:
                self.risky_payment.add(moment)

        if self._is_duplicate(content.text_hash, content.simhash):
            self.duplicates.add(moment)
        if content.text_hash is not None:
            self.recent_hashes.append(content.text_hash)
        if content.simhash is not None:
            self.recent_simhashes.append(content.simhash)

        if content.url_domains:
            self.with_link.add(moment)
            if any(domain in URL_SHORTENERS for domain in content.url_domains):
                self.with_shortener.add(moment)
            if self.blocked_domains.intersection(content.url_domains):
                self.with_blocked_domain.add(moment)
            if INVITE_DOMAINS.intersection(content.url_domains):
                self.with_invite.add(moment)
            for domain in content.url_domains:
                self.domains.add(moment, domain)

    def _is_duplicate(self, text_hash: str | None, simhash: int | None) -> bool:
        """An exact or near copy of something this actor wrote recently."""
        if text_hash is not None and text_hash in self.recent_hashes:
            return True
        if simhash is not None:
            return any(
                hamming_distance(simhash, other) <= NEAR_DUPLICATE_BITS
                for other in self.recent_simhashes
            )
        return False

    def busiest_space(self, as_of: datetime) -> str | None:
        """The space this actor posted in most during the hour before ``as_of``."""
        counts: dict[str, int] = {}
        for moment, space in self.recent_spaces:
            if as_of - HOUR <= moment < as_of:
                counts[space] = counts.get(space, 0) + 1
        return max(counts, key=lambda s: (counts[s], s)) if counts else None

    def record_listing_price(self, moment: datetime, share_of_usual: float) -> None:
        """A listing priced at ``share_of_usual`` of its category's usual price."""
        if share_of_usual < CHEAP_LISTING_SHARE:
            self.cheap_listings.add(moment)

    # -- what others do to this actor -------------------------------------------

    def apply_received(self, event: Event) -> None:
        """Called on the target owner's summary when someone else acts on their content."""
        moment = event.occurred_at
        if event.event_type is EventType.REPORT_FILED:
            self.reports_received.add(moment)
        elif (
            event.event_type is EventType.CONTENT_CREATED
            and event.content is not None
            and event.content.kind in (ContentKind.REPLY, ContentKind.MESSAGE)
            and event.target is not None
            and event.target.type is TargetType.CONTENT
        ):
            self.replies_received.add(moment)
        self._prune(moment)

    def _prune(self, newest: datetime) -> None:
        for counter in (
            self.activity,
            self.content,
            self.posts_written,
            self.replies_written,
            self.duplicates,
            self.with_link,
            self.with_shortener,
            self.with_blocked_domain,
            self.with_invite,
            self.interactions,
            self.reports_received,
            self.replies_received,
            self.text_checked,
            self.offsite_contact,
            self.risky_payment,
            self.cheap_listings,
        ):
            counter.prune(newest)
        for tally in (self.domains, self.spaces, self.hours):
            tally.prune(newest)
