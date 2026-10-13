"""The three simulated platforms.

Each platform writes its raw data the way a real export might: its own column
names, its own action names, its own file format and its own time format. The
matching ``configs/platforms/<name>.yaml`` files tell the adapters how to read
them back. Nothing in the rows reveals a user's persona.

| Platform          | Style       | File    | Time format                         |
|-------------------|-------------|---------|-------------------------------------|
| synthetic_forum   | Reddit-like | JSONL   | ISO 8601 UTC ("...Z")               |
| synthetic_chat    | Discord-like| Parquet | Unix epoch milliseconds             |
| synthetic_market  | Marketplace | CSV     | Local India time, no timezone       |
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from riskdetect.synthetic.actions import SynthAction as A
from riskdetect.synthetic.content import TextStyle

NOISE_ACTION = "debug_ping"  # an action no platform config maps; simulates junk rows
_IST = timedelta(hours=5, minutes=30)


@dataclass(frozen=True)
class ResolvedAction:
    """One simulated action with its target worked out, ready to be written as a row."""

    seq: int
    time: datetime
    actor_id: str
    action: A
    content_id: str | None = None
    text: str | None = None
    space: str | None = None
    target_id: str | None = None
    target_owner: str | None = None
    noise: bool = False


RowFormatter = Callable[["PlatformProfile", ResolvedAction], dict[str, Any]]


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    output_format: Literal["csv", "jsonl", "parquet"]
    columns: tuple[str, ...]
    actions: Mapping[A, str]  # simulator action -> this platform's raw action name
    spaces: tuple[str, ...]
    text_style: TextStyle
    activity: float  # multiplies actions per human session (chat is chattier)
    action_scale: Mapping[A, float]  # tilts persona action weights for this platform
    utc_offsets: tuple[float, ...]  # users' home timezones, in hours
    format_row: RowFormatter

    def raw_action(self, item: ResolvedAction) -> str:
        return NOISE_ACTION if item.noise else self.actions[item.action]

    def weight(self, action: A, base: float) -> float:
        """A persona's weight for an action on this platform (0 if unsupported)."""
        if action not in self.actions:
            return 0.0
        return base * self.action_scale.get(action, 1.0)


def _forum_row(profile: PlatformProfile, item: ResolvedAction) -> dict[str, Any]:
    return {
        "id": item.content_id or f"e{item.seq}",
        "author": item.actor_id,
        "kind": profile.raw_action(item),
        "ts": item.time.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "subforum": item.space,
        "body": item.text,
        "parent_id": item.target_id,
        "parent_author": item.target_owner,
        "lang": "en" if item.text else None,
    }


def _chat_row(profile: PlatformProfile, item: ResolvedAction) -> dict[str, Any]:
    return {
        "msg_id": item.content_id,  # reactions and joins have no ID in this export
        "user": item.actor_id,
        "event": profile.raw_action(item),
        "time_ms": int(item.time.timestamp() * 1000),
        "channel": item.space,
        "content": item.text,
        "reply_to": item.target_id,
        "reply_to_user": item.target_owner,
    }


def _market_row(profile: PlatformProfile, item: ResolvedAction) -> dict[str, Any]:
    is_listing = item.action is A.POST
    local = (item.time.astimezone(UTC) + _IST).replace(tzinfo=None)
    return {
        "listing_id": item.content_id if is_listing else None,
        "member_id": item.actor_id,
        "action": profile.raw_action(item),
        "created_time": local.strftime("%Y-%m-%d %H:%M:%S"),
        "category": item.space,
        "description": item.text,
        "price": (item.seq * 37) % 990 + 10 if is_listing else None,
        "target": item.target_id,
        "target_owner": item.target_owner,
    }


FORUM = PlatformProfile(
    name="synthetic_forum",
    output_format="jsonl",
    columns=(
        "id",
        "author",
        "kind",
        "ts",
        "subforum",
        "body",
        "parent_id",
        "parent_author",
        "lang",
    ),
    actions={
        A.SIGNUP: "signup",
        A.POST: "submission",
        A.REPLY: "comment",
        A.VOTE_UP: "upvote",
        A.VOTE_DOWN: "downvote",
        A.SAVE: "save",
        A.FOLLOW: "follow",
        A.REPORT: "report",
    },
    spaces=tuple(
        f"f/{name}"
        for name in (
            "news gaming music movies books tech science sports food travel "
            "photography diy fitness pets cars finance jobs art history askanything"
        ).split()
    ),
    text_style=TextStyle(8, 40),
    activity=1.0,
    action_scale={},
    utc_offsets=(-5.0, 0.0, 1.0, 5.5, 8.0),
    format_row=_forum_row,
)

CHAT = PlatformProfile(
    name="synthetic_chat",
    output_format="parquet",
    columns=(
        "msg_id",
        "user",
        "event",
        "time_ms",
        "channel",
        "content",
        "reply_to",
        "reply_to_user",
    ),
    actions={
        A.SIGNUP: "join",
        A.POST: "message",
        A.REPLY: "message",
        A.VOTE_UP: "react",
        A.REPORT: "report",
    },
    spaces=tuple(
        f"#{name}" for name in "general random help offtopic memes music gaming dev".split()
    ),
    text_style=TextStyle(2, 12),
    activity=3.0,
    action_scale={A.POST: 2.0, A.REPLY: 1.5},
    utc_offsets=(-8.0, -5.0, 0.0, 1.0, 5.5),
    format_row=_chat_row,
)

MARKET = PlatformProfile(
    name="synthetic_market",
    output_format="csv",
    columns=(
        "listing_id",
        "member_id",
        "action",
        "created_time",
        "category",
        "description",
        "price",
        "target",
        "target_owner",
    ),
    actions={
        A.SIGNUP: "register",
        A.POST: "new_listing",
        A.REPLY: "send_message",
        A.SAVE: "favorite",
        A.FOLLOW: "follow_seller",
        A.REPORT: "report",
    },
    spaces=tuple(
        "electronics phones fashion home books toys sports vehicles furniture services".split()
    ),
    text_style=TextStyle(6, 20),
    activity=0.6,
    action_scale={A.POST: 0.6, A.SAVE: 4.0},
    utc_offsets=(5.5,),
    format_row=_market_row,
)

PROFILES: dict[str, PlatformProfile] = {p.name: p for p in (FORUM, CHAT, MARKET)}
