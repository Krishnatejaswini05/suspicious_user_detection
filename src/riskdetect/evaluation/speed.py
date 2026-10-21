"""How fast bad users were caught live, and how much they posted first.

Measured from each bad user's first abusive post (their first content at or after
abuse_start), not from abuse_start itself: a bot can switch on hours before its
first burst, and there is nothing to detect until it acts.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any

from riskdetect.labels import TruthIndex
from riskdetect.schema import EventType
from riskdetect.storage import EventStore

FLAGGED_TIERS = frozenset({"REVIEW", "HIGH"})


@dataclass(frozen=True)
class Detection:
    platform: str
    actor_id: str
    segment: str | None
    first_abusive_post: datetime | None
    first_flag: datetime | None
    posts_before_flag: int | None

    @property
    def minutes(self) -> float | None:
        if self.first_abusive_post is None or self.first_flag is None:
            return None
        return (self.first_flag - self.first_abusive_post).total_seconds() / 60


@dataclass(frozen=True)
class SpeedSummary:
    segment: str
    caught: int
    total: int
    median_minutes: float | None
    max_minutes: float | None
    median_posts_before: float | None


def detections(
    history: Iterable[Mapping[str, Any]], truths: TruthIndex, store: EventStore
) -> list[Detection]:
    """One Detection per bad user (with a known abuse_start) on the history's platforms."""
    first_flag: dict[tuple[str, str], datetime] = {}
    platforms: set[str] = set()
    for row in history:
        platforms.add(row["platform"])
        key = (row["platform"], row["actor_id"])
        if row["tier"] in FLAGGED_TIERS and key not in first_flag:
            first_flag[key] = row["as_of"]

    out = []
    for (platform, actor), truth in sorted(truths.items()):
        start = truth.label.abuse_start if truth.label else None
        if platform not in platforms or start is None:
            continue
        posts = [
            e.occurred_at
            for e in store.get_actor_events(platform, actor, since=start)
            if e.event_type is EventType.CONTENT_CREATED
        ]
        flag = first_flag.get((platform, actor))
        out.append(
            Detection(
                platform=platform,
                actor_id=actor,
                segment=truth.segment,
                first_abusive_post=posts[0] if posts else None,
                first_flag=flag,
                posts_before_flag=sum(1 for t in posts if t < flag) if flag else None,
            )
        )
    return out


def summarize(found: Iterable[Detection]) -> list[SpeedSummary]:
    groups: dict[str, list[Detection]] = defaultdict(list)
    for detection in found:
        groups[detection.segment or "all"].append(detection)
    summaries = []
    for segment, group in sorted(groups.items()):
        minutes = [d.minutes for d in group if d.minutes is not None]
        posts = [d.posts_before_flag for d in group if d.posts_before_flag is not None]
        summaries.append(
            SpeedSummary(
                segment=segment,
                caught=sum(1 for d in group if d.first_flag is not None),
                total=len(group),
                median_minutes=median(minutes) if minutes else None,
                max_minutes=max(minutes) if minutes else None,
                median_posts_before=median(posts) if posts else None,
            )
        )
    return summaries
