"""Summary of one ingestion run."""

from collections import Counter
from dataclasses import dataclass, field

from riskdetect.schema import RejectionReason


@dataclass
class IngestReport:
    platform: str
    received: int = 0
    duplicates: int = 0
    rejections: Counter[RejectionReason] = field(default_factory=Counter)
    stored: int = 0
    late: int = 0
    very_late: int = 0
    actors_to_rescore: set[str] = field(default_factory=set)
    published: int = 0

    @property
    def rejected(self) -> int:
        return sum(self.rejections.values())

    def summary(self) -> str:
        lines = [
            f"Ingest:            {self.platform}",
            f"Received:          {self.received:,}",
            f"Duplicates:        {self.duplicates:,}  (skipped)",
            f"Rejected:          {self.rejected:,}  (quarantined)",
        ]
        for reason, count in self.rejections.most_common():
            lines.append(f"  {reason}: {count:,}")
        lines += [
            f"Stored:            {self.stored:,}",
            f"Late events:       {self.late:,}  "
            f"({len(self.actors_to_rescore):,} actors to rescore)",
            f"Very late:         {self.very_late:,}",
            f"Published:         {self.published:,}",
        ]
        return "\n".join(lines)
