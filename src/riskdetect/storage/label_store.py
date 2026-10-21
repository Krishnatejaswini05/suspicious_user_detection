"""Label store: decisions about users (e.g. from reviewers), appended as Parquet.

Layout: ``labels/reviews/part-<id>.parquet``. Reviewer decisions become training
labels for the next model: this is how the system keeps learning on each platform.
"""

import uuid
from pathlib import Path
from typing import Any

from riskdetect.schema import Label
from riskdetect.storage.parquet import TIMESTAMPTZ, read_parquet, write_parquet

LABEL_SCHEMA = {
    "actor_id": "VARCHAR",
    "platform": "VARCHAR",
    "category": "VARCHAR",
    "abuse_start": TIMESTAMPTZ,
    "decided_at": TIMESTAMPTZ,
    "source": "VARCHAR",
    "confidence": "DOUBLE",
}
# Audit columns kept next to each label (who decided, and why); not part of Label itself.
AUDIT_SCHEMA = {"reviewer": "VARCHAR", "note": "VARCHAR"}


class ParquetLabelStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def append(self, labels: list[Label], extra: list[dict[str, Any]] | None = None) -> int:
        """Save labels; ``extra`` holds one audit dict (reviewer, note) per label."""
        if not labels:
            return 0
        audits = extra or [{} for _ in labels]
        if len(audits) != len(labels):
            raise ValueError("extra must have one entry per label")
        rows = []
        for label, audit in zip(labels, audits, strict=True):
            row = label.model_dump(mode="python")
            row["category"] = str(row["category"])
            row["source"] = str(row["source"])
            row.update({key: audit.get(key) for key in AUDIT_SCHEMA})
            rows.append(row)
        name = f"part-{uuid.uuid4().hex[:16]}.parquet"  # short: Windows limits path length
        return write_parquet(self.directory / name, rows, {**LABEL_SCHEMA, **AUDIT_SCHEMA})

    def audit_log(self, platform: str | None = None) -> list[dict[str, Any]]:
        """Every saved decision with its reviewer and note, oldest first."""
        if not self.directory.is_dir() or not any(self.directory.glob("*.parquet")):
            return []
        where, params = ("platform = ?", [platform]) if platform else ("", [])
        return list(
            read_parquet(
                (self.directory / "*.parquet").as_posix(),
                where=where,
                params=params,
                order_by="decided_at, actor_id",
            )
        )

    def read(self, platform: str | None = None) -> list[Label]:
        if not self.directory.is_dir() or not any(self.directory.glob("*.parquet")):
            return []
        where, params = ("platform = ?", [platform]) if platform else ("", [])
        rows = read_parquet(
            (self.directory / "*.parquet").as_posix(),
            where=where,
            params=params,
            order_by="decided_at, actor_id",
            columns=list(LABEL_SCHEMA),
        )
        return [Label.model_validate(row) for row in rows]
