"""The "fix me" tray: rejected records with their reasons, kept for repair and reload.

Records here have already had private text columns removed by the adapter.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from riskdetect.schema import Rejection, RejectionReason
from riskdetect.storage.interfaces import QuarantinedRecord

_SCHEMA = pa.schema(
    [
        ("platform", pa.string()),
        ("quarantined_at", pa.timestamp("us", tz="UTC")),
        ("reason", pa.string()),
        ("detail", pa.string()),
        ("fields", pa.list_(pa.string())),
        ("raw", pa.string()),  # JSON of the original record, minus private text
    ]
)


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
        folder = self.directory / f"platform={platform}"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"part-{uuid.uuid4().hex[:16]}.parquet"  # short: Windows limits path length
        pq.write_table(pa.Table.from_pylist(rows, schema=_SCHEMA), folder / name)
        return len(rows)

    def read(self, platform: str | None = None) -> list[QuarantinedRecord]:
        base = self.directory / f"platform={platform}" if platform else self.directory
        if not base.is_dir():
            return []
        records = []
        for file in sorted(base.glob("**/*.parquet")):
            for row in pq.read_table(file).to_pylist():
                rejection = Rejection(
                    reason=RejectionReason(row["reason"]),
                    detail=row["detail"],
                    fields=tuple(row["fields"] or ()),
                    raw=json.loads(row["raw"]) if row["raw"] is not None else None,
                )
                records.append(QuarantinedRecord(row["platform"], row["quarantined_at"], rejection))
        return records
