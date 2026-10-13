"""The simulator's own action vocabulary.

Personas decide *what kind* of thing to do using these platform-neutral actions.
Each platform profile then writes them out under its own raw names
(``POST`` becomes ``submission`` on the forum, ``message`` in chat, ``new_listing``
on the marketplace), which is exactly what the adapters must translate back.
"""

from enum import StrEnum


class SynthAction(StrEnum):
    SIGNUP = "signup"
    POST = "post"
    REPLY = "reply"
    VOTE_UP = "vote_up"
    VOTE_DOWN = "vote_down"
    SAVE = "save"
    FOLLOW = "follow"
    REPORT = "report"


CREATES_CONTENT = frozenset({SynthAction.POST, SynthAction.REPLY})
TARGETS_CONTENT = frozenset(
    {
        SynthAction.REPLY,
        SynthAction.VOTE_UP,
        SynthAction.VOTE_DOWN,
        SynthAction.SAVE,
        SynthAction.REPORT,
    }
)
