"""The "fix me" tray: rejected records with their reasons, kept for repair and reload.

Records here have already had private text columns removed by the adapter.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from riskdetect.schema import Rejection, RejectionReason
from riskdetect.storage.interfaces import QuarantinedRecord
from riskdetect.storage.parquet import TIMESTAMPTZ, read_parquet, write_parquet

_SCHEMA = {
    "platform": "VARCHAR",
    "quarantined_at": TIMESTAMPTZ,
    "reason": "VARCHAR",
    "detail": "VARCHAR",
    "fields": "VARCHAR[]",
    "raw": "VARCHAR",  # JSON of the original record, minus private text
}


class ParquetQuarantineStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def append(self, platform: str, rejections: list[Rejection], at: datetime) -> int:
        if not rejections:
            return 0
        rows = [
            {
                "platform": platform,
                "quarantined_at": at,
                "reason": str(r.reason),
                "detail": r.detail,
                "fields": list(r.fields),
                "raw": json.dumps(dict(r.raw), default=str) if r.raw is not None else None,
            }
            for r in rejections
        ]
        name = f"part-{uuid.uuid4().hex[:16]}.parquet"  # short: Windows limits path length
        return write_parquet(self.directory / f"platform={platform}" / name, rows, _SCHEMA)

    def read(self, platform: str | None = None) -> list[QuarantinedRecord]:
        base = self.directory / f"platform={platform}" if platform else self.directory
        if not base.is_dir():
            return []
        records = []
        for file in sorted(base.glob("**/*.parquet")):
            for row in read_parquet(file):
                rejection = Rejection(
                    reason=RejectionReason(row["reason"]),
                    detail=row["detail"],
                    fields=tuple(row["fields"] or ()),
                    raw=json.loads(row["raw"]) if row["raw"] is not None else None,
                )
                records.append(QuarantinedRecord(row["platform"], row["quarantined_at"], rejection))
        return records
