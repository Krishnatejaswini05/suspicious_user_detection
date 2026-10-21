"""Types of simulated users and how each behaves.

Good personas that look a little unusual (enthusiastic new user, power user,
lurker, expert linker, maintainer) matter as much as the bad ones: they test that
the detector does NOT flag innocent people. The enthusiastic new user is the key
fairness case. The expert linker and the maintainer come from the first real data
(monero.stackexchange.com): trusted members who always link to sources, and who
sometimes have a very busy day - answering a pile of questions, or telling many
threads that a page has moved.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from riskdetect.schema import LabelCategory
from riskdetect.synthetic.actions import SynthAction as A


class PersonaName(StrEnum):
    NORMAL = "normal"
    ENTHUSIASTIC_NEW = "enthusiastic_new"
    POWER_USER = "power_user"
    LURKER = "lurker"
    SPAM_BOT = "spam_bot"
    SLOW_SPAMMER = "slow_spammer"
    HIJACKED = "hijacked"
    EXPERT_LINKER = "expert_linker"
    MAINTAINER = "maintainer"


@dataclass(frozen=True)
class HumanHabits:
    """Human-style activity: sessions during waking hours, varied actions."""

    sessions_per_day: float
    actions_per_session: float
    weights: Mapping[A, float]  # relative chance of each action within a session
    link_rate: float  # share of posts/replies that contain a link
    home_spaces: tuple[int, int]  # how many spaces the user is active in (min, max)
    link_domains: tuple[str, ...] | None = None  # sites they link to; None = everyday mix


@dataclass(frozen=True)
class BusyDays:
    """A few personal days of much more activity than usual (innocent, not abuse)."""

    count: tuple[int, int]  # how many such days in the window (min, max)
    boost: float  # how many times the usual sessions
    notices: bool = False  # spend the day replying "this has moved, see <link>"


@dataclass(frozen=True)
class BotHabits:
    """Automated activity: bursts at near-fixed intervals, at any hour."""

    bursts_per_day: tuple[float, float]
    burst_size: tuple[int, int]
    interval_seconds: tuple[float, float]  # per-bot base gap between actions
    reply_share: float  # share of spam posted as replies in other people's threads


@dataclass(frozen=True)
class PersonaSpec:
    name: PersonaName
    category: LabelCategory
    # Accounts created before the simulation window: age range in days.
    # None means the account is created during the window, at a share of it in this range.
    account_age_days: tuple[float, float] | None
    created_in_window: tuple[float, float]
    habits: HumanHabits
    # When abuse begins, as a share of the window (or days after creation for new bots).
    abuse_start: tuple[float, float] | None = None
    bot: BotHabits | None = None
    busy: BusyDays | None = None

    @property
    def is_bad(self) -> bool:
        return self.category is not LabelCategory.CLEAN


_NORMAL_WEIGHTS = {
    A.POST: 0.15,
    A.REPLY: 0.25,
    A.VOTE_UP: 0.42,
    A.VOTE_DOWN: 0.05,
    A.SAVE: 0.08,
    A.FOLLOW: 0.03,
    A.REPORT: 0.02,
}
_DOCS_DOMAINS = ("docs.example.org", "github.com", "wikipedia.org")
_SPAM_BURSTS = BotHabits(
    bursts_per_day=(2.0, 5.0),
    burst_size=(5, 20),
    interval_seconds=(5.0, 30.0),
    reply_share=0.15,
)

PERSONAS: dict[PersonaName, PersonaSpec] = {
    PersonaName.NORMAL: PersonaSpec(
        name=PersonaName.NORMAL,
        category=LabelCategory.CLEAN,
        account_age_days=(30, 1500),
        created_in_window=(0, 0),
        habits=HumanHabits(1.2, 4.0, _NORMAL_WEIGHTS, link_rate=0.08, home_spaces=(2, 5)),
    ),
    PersonaName.ENTHUSIASTIC_NEW: PersonaSpec(
        name=PersonaName.ENTHUSIASTIC_NEW,
        category=LabelCategory.CLEAN,
        account_age_days=None,
        # Join throughout the window, so every test period contains genuinely new,
        # innocent accounts for the fairness checks.
        created_in_window=(0.0, 0.95),
        habits=HumanHabits(
            3.0,
            7.0,
            {**_NORMAL_WEIGHTS, A.POST: 0.25, A.REPLY: 0.35, A.VOTE_UP: 0.30},
            link_rate=0.10,
            home_spaces=(3, 8),
        ),
    ),
    PersonaName.POWER_USER: PersonaSpec(
        name=PersonaName.POWER_USER,
        category=LabelCategory.CLEAN,
        account_age_days=(300, 2000),
        created_in_window=(0, 0),
        habits=HumanHabits(
            5.0,
            8.0,
            {**_NORMAL_WEIGHTS, A.POST: 0.22, A.REPLY: 0.35, A.VOTE_UP: 0.33},
            link_rate=0.15,
            home_spaces=(5, 15),
        ),
    ),
    PersonaName.LURKER: PersonaSpec(
        name=PersonaName.LURKER,
        category=LabelCategory.CLEAN,
        account_age_days=(30, 1500),
        created_in_window=(0, 0),
        habits=HumanHabits(
            1.0,
            5.0,
            {A.POST: 0.02, A.REPLY: 0.03, A.VOTE_UP: 0.80, A.SAVE: 0.12, A.FOLLOW: 0.03},
            link_rate=0.05,
            home_spaces=(1, 4),
        ),
    ),
    PersonaName.SPAM_BOT: PersonaSpec(
        name=PersonaName.SPAM_BOT,
        category=LabelCategory.BOT,
        account_age_days=None,
        created_in_window=(0.0, 0.6),
        habits=HumanHabits(0.5, 2.0, _NORMAL_WEIGHTS, link_rate=0.0, home_spaces=(1, 2)),
        abuse_start=(0.02, 0.5),  # days after the account is created
        bot=_SPAM_BURSTS,
    ),
    PersonaName.SLOW_SPAMMER: PersonaSpec(
        name=PersonaName.SLOW_SPAMMER,
        category=LabelCategory.SPAM,
        account_age_days=(5, 300),
        created_in_window=(0, 0),
        habits=HumanHabits(
            1.5,
            2.5,
            {A.POST: 0.65, A.REPLY: 0.20, A.VOTE_UP: 0.15},
            link_rate=1.0,
            home_spaces=(2, 6),
        ),
        abuse_start=(0.0, 0.3),  # share of the window
    ),
    PersonaName.HIJACKED: PersonaSpec(
        name=PersonaName.HIJACKED,
        category=LabelCategory.HIJACKED,
        account_age_days=(200, 1500),
        created_in_window=(0, 0),
        habits=HumanHabits(1.2, 4.0, _NORMAL_WEIGHTS, link_rate=0.08, home_spaces=(2, 5)),
        abuse_start=(0.4, 0.75),  # share of the window
        bot=BotHabits(
            bursts_per_day=(2.0, 4.0),
            burst_size=(5, 15),
            interval_seconds=(10.0, 45.0),
            reply_share=0.3,
        ),
    ),
    PersonaName.EXPERT_LINKER: PersonaSpec(
        name=PersonaName.EXPERT_LINKER,
        category=LabelCategory.CLEAN,
        account_age_days=(200, 2000),
        created_in_window=(0, 0),
        habits=HumanHabits(
            1.5,
            4.0,
            {**_NORMAL_WEIGHTS, A.POST: 0.10, A.REPLY: 0.45, A.VOTE_UP: 0.30},
            link_rate=0.75,  # answers cite documentation and sources
            home_spaces=(2, 6),
            link_domains=_DOCS_DOMAINS,
        ),
        busy=BusyDays(count=(1, 3), boost=6.0),  # an answering spree
    ),
    PersonaName.MAINTAINER: PersonaSpec(
        name=PersonaName.MAINTAINER,
        category=LabelCategory.CLEAN,
        account_age_days=(300, 2000),
        created_in_window=(0, 0),
        habits=HumanHabits(
            1.2,
            4.0,
            _NORMAL_WEIGHTS,
            link_rate=0.30,
            home_spaces=(3, 8),
            link_domains=_DOCS_DOMAINS,
        ),
        busy=BusyDays(count=(1, 2), boost=6.0, notices=True),  # "the docs moved" day
    ),
}
