"""Score store: risk scores per platform, as Parquet.

Layout: ``scores/platform=<platform>/<name>.parquet``. A batch scoring run writes
one table (replacing the previous run's). Realtime scoring (later) will append
history so trends ("risk is rising") can be shown.
"""

from pathlib import Path
from typing import Any

from riskdetect.storage.parquet import TIMESTAMPTZ, read_all, write_parquet

SCORE_SCHEMA = {
    "platform": "VARCHAR",
    "actor_id": "VARCHAR",
    "as_of": TIMESTAMPTZ,
    "score": "DOUBLE",
    "tier": "VARCHAR",
    "confidence": "VARCHAR",
    "categories": "VARCHAR",  # JSON
    "reasons": "VARCHAR[]",
    "reason_codes": "VARCHAR[]",
    "rules_fired": "VARCHAR[]",
    "shadow_rules": "VARCHAR[]",
    "actions": "VARCHAR[]",
    "rules_version": "INTEGER",
    "scoring_version": "INTEGER",
}


class ParquetScoreStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, platform: str, name: str = "scores") -> Path:
        return self.directory / f"platform={platform}" / f"{name}.parquet"

    def write(self, platform: str, rows: list[dict[str, Any]], name: str = "scores") -> Path:
        path = self.path(platform, name)
        write_parquet(path, rows, SCORE_SCHEMA)
        return path

    def read(self, platform: str, name: str = "scores") -> list[dict[str, Any]]:
        path = self.path(platform, name)
        return read_all(path) if path.exists() else []
