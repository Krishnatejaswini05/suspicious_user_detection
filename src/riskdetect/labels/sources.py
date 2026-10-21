"""Where labels come from.

v1: the simulator's answer key, which is complete and exact. Later: reviewer
decisions, moderator actions and appeals, each with its own confidence.
"""

from pathlib import Path

from riskdetect.labels.outcomes import ActorTruth, TruthIndex
from riskdetect.synthetic import read_answer_key


def truths_from_answer_key(path: Path) -> TruthIndex:
    """Every simulated user's truth, with their persona as the reporting segment."""
    return {
        (entry.label.platform, entry.label.actor_id): ActorTruth(
            platform=entry.label.platform,
            actor_id=entry.label.actor_id,
            label=entry.label,
            segment=str(entry.persona),
        )
        for entry in read_answer_key(path)
    }
