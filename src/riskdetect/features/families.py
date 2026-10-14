"""The v1 behavioral features.

Every formula reads an actor's running summary *as of* a moment, and the summary
only ever contains events from before that moment. Account age is deliberately
just one feature among many; it is never a verdict on its own.
"""

from datetime import datetime
from itertools import pairwise
from statistics import mean, median, pstdev

from riskdetect.features.definition import Feature, FeatureValue
from riskdetect.features.state import ActorState
from riskdetect.features.windows import DAY, HOUR, MONTH, WEEK, day_index

_MIN_GAPS = 5  # timing measures need a handful of gaps to mean anything
_MIN_BASELINE_DAYS = 3
_MIN_LINKS_FOR_SHARE = 3
_DORMANCY_LOOKBACK_DAYS = 60

# -- lifecycle -----------------------------------------------------------------


def _account_age_days(s: ActorState, as_of: datetime) -> FeatureValue:
    start = s.created_at or s.first_seen
    return None if start is None else (as_of - start).total_seconds() / 86400


def _hours_to_first_post(s: ActorState, as_of: datetime) -> FeatureValue:
    if s.created_at is None or s.first_content_at is None:
        return None
    return (s.first_content_at - s.created_at).total_seconds() / 3600


# -- timing --------------------------------------------------------------------


def _timing_regularity(s: ActorState, as_of: datetime) -> FeatureValue:
    """1 = gaps between actions are nearly identical (machine-like); near 0 = irregular."""
    gaps = list(s.gaps_seconds)
    if len(gaps) < _MIN_GAPS:
        return None
    middle = median(gaps)
    if middle == 0:
        return 1.0
    spread = median(abs(g - middle) for g in gaps)
    return 1.0 - min(1.0, spread / middle)


def _burstiness(s: ActorState, as_of: datetime) -> FeatureValue:
    """-1 = perfectly regular, 0 = random, towards 1 = activity in sudden clumps."""
    gaps = list(s.gaps_seconds)
    if len(gaps) < _MIN_GAPS:
        return None
    mu, sigma = mean(gaps), pstdev(gaps)
    return None if mu + sigma == 0 else (sigma - mu) / (sigma + mu)


def _active_hours_7d(s: ActorState, as_of: datetime) -> FeatureValue:
    """Distinct hours of the day with activity in the last 7 days (24 = never sleeps)."""
    hours = s.hours.totals(WEEK, as_of)
    return float(len(hours)) if hours else None


# -- change against the actor's own past ----------------------------------------


def _rate_vs_baseline(s: ActorState, as_of: datetime) -> FeatureValue:
    """Last 24h activity relative to this actor's usual daily activity (smoothed)."""
    if s.first_active is None:
        return None
    today = day_index(as_of)
    # From first activity, not signup: days before anything happened are not "usual quiet".
    first_day = max(day_index(s.first_active), today - MONTH.days)
    history_days = range(first_day, today)  # whole days before today
    if len(history_days) < _MIN_BASELINE_DAYS:
        return None  # too new to have a "usual"; missing, not suspicious
    daily = s.activity.daily_totals()
    baseline = sum(daily.get(d, 0) for d in history_days) / len(history_days)
    return (s.activity.count(DAY, as_of) + 1) / (baseline + 1)


def _dormancy_gap_days(s: ActorState, as_of: datetime) -> FeatureValue:
    """Longest run of inactive days between active days in the last 60 days."""
    today = day_index(as_of)
    active = sorted(
        d
        for d, n in s.activity.daily_totals().items()
        if n and today - _DORMANCY_LOOKBACK_DAYS <= d <= today
    )
    if len(active) < 2:
        return None
    return float(max(b - a - 1 for a, b in pairwise(active)))


# -- content -------------------------------------------------------------------


def _ratio(numerator: int, denominator: int) -> FeatureValue:
    return None if denominator == 0 else numerator / denominator


def _top_domain_share_7d(s: ActorState, as_of: datetime) -> FeatureValue:
    """Share of links pointing at the most-used domain (1 = always the same site)."""
    counts = s.domains.totals(WEEK, as_of)
    total = sum(counts.values())
    if total < _MIN_LINKS_FOR_SHARE:
        return None
    return max(counts.values()) / total


FEATURES: tuple[Feature, ...] = (
    # lifecycle
    Feature(
        "account_age_days", 1, "lifecycle",
        "Days since the account was created (or first seen). Never a verdict on its own.",
        _account_age_days,
    ),
    Feature(
        "hours_to_first_post", 1, "lifecycle",
        "Hours between account creation and its first post.",
        _hours_to_first_post, requires=frozenset({"content"}),
    ),
    # volume
    Feature(
        "posts_1h", 1, "volume", "Posts, replies, messages or listings in the last hour.",
        lambda s, t: float(s.content.count(HOUR, t)),
        requires=frozenset({"content"}), percentile=True,
    ),
    Feature(
        "posts_24h", 1, "volume", "Content created in the last 24 hours.",
        lambda s, t: float(s.content.count(DAY, t)),
        requires=frozenset({"content"}), percentile=True,
    ),
    Feature(
        "posts_7d", 1, "volume", "Content created in the last 7 days.",
        lambda s, t: float(s.content.count(WEEK, t)),
        requires=frozenset({"content"}), percentile=True,
    ),
    Feature(
        "interactions_24h", 1, "volume", "Votes, reactions, saves and follows in the last 24h.",
        lambda s, t: float(s.interactions.count(DAY, t)),
        requires=frozenset({"interactions"}), percentile=True,
    ),
    Feature(
        "interactions_7d", 1, "volume", "Votes, reactions, saves and follows in the last 7 days.",
        lambda s, t: float(s.interactions.count(WEEK, t)),
        requires=frozenset({"interactions"}), percentile=True,
    ),
    Feature(
        "events_24h", 1, "volume", "All activity in the last 24 hours.",
        lambda s, t: float(s.activity.count(DAY, t)),
        percentile=True,
    ),
    # timing
    Feature(
        "timing_regularity", 1, "timing",
        "How alike the gaps between actions are: 1 = machine-like, near 0 = human-irregular.",
        _timing_regularity,
    ),
    Feature(
        "burstiness", 1, "timing",
        "Whether activity comes in sudden clumps (towards 1) or evenly (towards -1).",
        _burstiness,
    ),
    Feature(
        "active_hours_7d", 1, "timing",
        "Distinct hours of the day with activity in the last 7 days (24 = never sleeps).",
        _active_hours_7d,
    ),
    # change
    Feature(
        "rate_vs_baseline", 1, "change",
        "Last 24h activity relative to this actor's own usual daily activity.",
        _rate_vs_baseline,
    ),
    Feature(
        "dormancy_gap_days", 1, "change",
        "Longest run of inactive days between active days in the last 60 days.",
        _dormancy_gap_days,
    ),
    # content
    Feature(
        "duplicate_ratio_24h", 1, "content",
        "Share of the last 24h's posts that copy (or nearly copy) the actor's recent posts.",
        lambda s, t: _ratio(s.duplicates.count(DAY, t), s.content.count(DAY, t)),
        requires=frozenset({"content", "text"}),
    ),
    Feature(
        "duplicate_ratio_7d", 1, "content",
        "Share of the last 7 days' posts that copy (or nearly copy) recent posts.",
        lambda s, t: _ratio(s.duplicates.count(WEEK, t), s.content.count(WEEK, t)),
        requires=frozenset({"content", "text"}),
    ),
    Feature(
        "link_ratio_7d", 1, "content", "Share of the last 7 days' posts that contain a link.",
        lambda s, t: _ratio(s.with_link.count(WEEK, t), s.content.count(WEEK, t)),
        requires=frozenset({"content", "urls"}),
    ),
    Feature(
        "shortener_ratio_7d", 1, "content",
        "Share of the last 7 days' posts that use a URL shortener such as bit.ly.",
        lambda s, t: _ratio(s.with_shortener.count(WEEK, t), s.content.count(WEEK, t)),
        requires=frozenset({"content", "urls"}),
    ),
    Feature(
        "distinct_domains_7d", 1, "content", "Different websites linked in the last 7 days.",
        lambda s, t: float(len(s.domains.totals(WEEK, t))),
        requires=frozenset({"content", "urls"}),
    ),
    Feature(
        "top_domain_share_7d", 1, "content",
        "Share of links that go to the single most-linked website (1 = always the same).",
        _top_domain_share_7d, requires=frozenset({"content", "urls"}),
    ),
    Feature(
        "distinct_spaces_7d", 1, "content",
        "Different communities, channels or categories used in the last 7 days.",
        lambda s, t: float(len(s.spaces.totals(WEEK, t))),
        requires=frozenset({"space_id"}), percentile=True,
    ),
    # how others respond
    Feature(
        "reports_received_7d", 1, "response",
        "Reports filed by others against this actor's content in the last 7 days.",
        lambda s, t: float(s.reports_received.count(WEEK, t)),
        requires=frozenset({"reports", "target_owner_id"}), percentile=True,
    ),
    Feature(
        "replies_per_post_7d", 1, "response",
        "Replies received per post in the last 7 days (spam rarely gets real replies).",
        lambda s, t: _ratio(s.replies_received.count(WEEK, t), s.content.count(WEEK, t)),
        requires=frozenset({"content", "target_owner_id"}),
    ),
    # evidence
    Feature(
        "events_seen", 1, "evidence",
        "Total events seen for this actor. Drives confidence, never risk.",
        lambda s, t: float(s.events_seen),
    ),
)  # fmt: skip
