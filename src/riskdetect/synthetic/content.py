"""What simulated users write.

Normal users write varied text (every post fingerprints differently) and
occasionally share ordinary links. Spammers repeat a few templates with small
changes and always push the same link, producing exact and near duplicates.
"""

import random
from dataclasses import dataclass

_WORDS = (
    "the a this that it is was are be have had do did not just really very so too also "
    "today yesterday tomorrow week time day night morning people friend team family work "
    "home city game music movie book food coffee tea weather rain sun trip travel photo "
    "idea question answer problem help thanks great good bad nice cool funny weird new "
    "old first last best worst think know feel want need like love hate try make take "
    "give find tell ask see look watch read write play learn build fix use start stop "
    "open close buy sell price cheap expensive quality size color phone laptop bike car "
    "shoes jacket table chair lamp garden kitchen recipe dinner lunch breakfast school "
    "class exam project code bug release update version news story event match season "
    "player coach goal score win lose draw anyone everyone someone nobody maybe probably "
    "always never sometimes again still already almost enough about after before during "
    "while"
).split()

_BENIGN_DOMAINS = (
    "youtube.com",
    "wikipedia.org",
    "github.com",
    "imgur.com",
    "stackoverflow.com",
    "news.example.org",
    "medium.com",
    "bbc.co.uk",
)


@dataclass(frozen=True)
class TextStyle:
    min_words: int
    max_words: int


@dataclass(frozen=True)
class Campaign:
    """A spam campaign: a few message templates pushing one set of domains."""

    name: str
    templates: tuple[str, ...]
    domains: tuple[str, ...]


CAMPAIGNS = (
    Campaign(
        "phones",
        (
            "Cheap phones today only! visit {link}",
            "Best phone deals, huge discount {link}",
            "Phones at 70% off, limited stock {link}",
        ),
        ("bit.ly", "phone-deals.shop"),
    ),
    Campaign(
        "crypto",
        (
            "Earn 500 dollars a day with crypto, join now {link}",
            "Crypto signals that never lose, free trial {link}",
        ),
        ("tinyurl.com", "coin-profit.xyz"),
    ),
    Campaign(
        "followers",
        (
            "Get 10k followers fast {link}",
            "Grow your account instantly, real followers {link}",
        ),
        ("grow-fast.top",),
    ),
    Campaign(
        "giveaway",
        (
            "You won a free gift card, claim here {link}",
            "Congratulations! claim your prize now {link}",
        ),
        ("bit.ly", "prize-claim.site"),
    ),
)


def normal_text(rng: random.Random, style: TextStyle, link_rate: float) -> str:
    """Varied everyday text; sometimes a mention or an ordinary link."""
    words = rng.choices(_WORDS, k=rng.randint(style.min_words, style.max_words))
    text = " ".join(words).capitalize() + rng.choice((".", ".", "!", "?"))
    if rng.random() < 0.05:
        text += f" @user{rng.randint(1, 999)}"
    if rng.random() < link_rate:
        path = "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
        text += f" https://{rng.choice(_BENIGN_DOMAINS)}/{path}"
    return text


def spam_link(rng: random.Random, campaign: Campaign) -> str:
    """The link one spammer keeps pushing (fixed per spammer, so posts repeat exactly)."""
    token = "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=6))
    domain = rng.choice(campaign.domains)
    return f"{domain}/{token}" if rng.random() < 0.5 else f"https://{domain}/{token}"


def spam_text(rng: random.Random, campaign: Campaign, link: str) -> str:
    """A campaign message. Mostly exact repeats, sometimes lightly changed."""
    text = rng.choice(campaign.templates).format(link=link)
    if rng.random() < 0.3:
        text = rng.choice(
            (
                text.replace("!", "!!"),
                text + " hurry",
                text.upper(),
                text.replace(",", ""),
                "Hey " + text,
            )
        )
    return text
