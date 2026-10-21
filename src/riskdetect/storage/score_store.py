"""Score store: risk scores per platform, as Parquet.

Two layouts:
- ``scores/platform=<platform>/<name>.parquet``: one table per batch scoring run,
  replacing the previous run's.
- ``scores/history/platform=<platform>/date=<YYYY-MM-DD>/part-*.parquet``: every live
  score, appended, so trends ("risk is rising") and time-to-detect can be shown.
"""

from pathlib import Path
from typing import Any

from riskdetect.storage.parquet import (
    TIMESTAMPTZ,
    read_all,
    read_parquet,
    write_parquet,
    write_partitioned,
)

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
    "signals": "VARCHAR[]",
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

    # -- live score history ----------------------------------------------------

    @property
    def history_directory(self) -> Path:
        return self.directory / "history"

    def append_history(self, rows: list[dict[str, Any]]) -> int:
        dated = [{**row, "date": row["as_of"].date().isoformat()} for row in rows]
        schema = {**SCORE_SCHEMA, "date": "VARCHAR"}
        return write_partitioned(self.history_directory, dated, schema, ("platform", "date"))

    def read_history(self, platform: str) -> list[dict[str, Any]]:
        """All live scores for a platform, oldest first."""
        base = self.history_directory / f"platform={platform}"
        if not base.is_dir() or not any(base.glob("**/*.parquet")):
            return []
        rows = read_parquet(
            (base / "**" / "*.parquet").as_posix(),
            order_by="as_of, actor_id",
            columns=list(SCORE_SCHEMA),
        )
        return list(rows)
