"""Closed sets of values used by the canonical schema.

These lists are deliberately small and platform-neutral. A new platform must map
its own actions onto them; the lists do not grow per platform. Anything that
does not fit belongs in an event's ``attributes``.
"""

from enum import StrEnum


class EventType(StrEnum):
    """What happened."""

    ACCOUNT_CREATED = "ACCOUNT_CREATED"
    CONTENT_CREATED = "CONTENT_CREATED"
    CONTENT_EDITED = "CONTENT_EDITED"
    CONTENT_DELETED = "CONTENT_DELETED"
    INTERACTION = "INTERACTION"
    REPORT_FILED = "REPORT_FILED"
    MODERATION_ACTION = "MODERATION_ACTION"
    PROFILE_UPDATED = "PROFILE_UPDATED"


class ContentKind(StrEnum):
    """The kind of thing a user created."""

    POST = "post"
    REPLY = "reply"
    MESSAGE = "message"
    LISTING = "listing"
    MEDIA = "media"


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class InteractionKind(StrEnum):
    """How a user reacted to something."""

    VOTE_UP = "vote_up"
    VOTE_DOWN = "vote_down"
    REACT = "react"
    FOLLOW = "follow"
    SHARE = "share"
    SAVE = "save"


class TargetType(StrEnum):
    """What an event is aimed at."""

    ACTOR = "actor"
    CONTENT = "content"
    SPACE = "space"


class ModerationActionType(StrEnum):
    REMOVE_CONTENT = "remove_content"
    RESTORE_CONTENT = "restore_content"
    WARN = "warn"
    RATE_LIMIT = "rate_limit"
    SUSPEND = "suspend"
    BAN = "ban"
    UNBAN = "unban"


class ModerationSource(StrEnum):
    AUTO = "auto"
    HUMAN = "human"


class SpaceKind(StrEnum):
    """A place where activity happens (subreddit, server channel, market category...)."""

    COMMUNITY = "community"
    CHANNEL = "channel"
    CATEGORY = "category"
    CONVERSATION = "conversation"
    OTHER = "other"


class LabelCategory(StrEnum):
    """Ground-truth verdict about an actor."""

    CLEAN = "clean"
    SPAM = "spam"
    BOT = "bot"
    HIJACKED = "hijacked"
    SCAM = "scam"
    COORDINATED = "coordinated"


class LabelSource(StrEnum):
    """Who produced a label. Sources differ in how much they can be trusted."""

    SYNTHETIC = "synthetic"
    REVIEWER = "reviewer"
    MODERATOR = "moderator"
    CONTENT_REMOVAL = "content_removal"
    APPEAL = "appeal"
