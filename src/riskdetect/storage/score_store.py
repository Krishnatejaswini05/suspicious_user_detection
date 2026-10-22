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

    def read_actor(
        self, platform: str, actor_id: str, name: str = "scores"
    ) -> list[dict[str, Any]]:
        """One user's rows from a batch scoring run, oldest first (without reading the rest)."""
        path = self.path(platform, name)
        if not path.exists():
            return []
        rows = read_parquet(
            path.as_posix(),
            where="actor_id = ?",
            params=[actor_id],
            order_by="as_of",
            columns=list(SCORE_SCHEMA),
        )
        return list(rows)

    # -- live score history ----------------------------------------------------

    @property
    def history_directory(self) -> Path:
        return self.directory / "history"

    def append_history(self, rows: list[dict[str, Any]]) -> int:
        dated = [{**row, "date": row["as_of"].date().isoformat()} for row in rows]
        schema = {**SCORE_SCHEMA, "date": "VARCHAR"}
        return write_partitioned(self.history_directory, dated, schema, ("platform", "date"))

    def read_history(self, platform: str, actor_id: str | None = None) -> list[dict[str, Any]]:
        """Live scores for a platform (optionally one user), oldest first."""
        base = self.history_directory / f"platform={platform}"
        if not base.is_dir() or not any(base.glob("**/*.parquet")):
            return []
        where, params = ("actor_id = ?", [actor_id]) if actor_id is not None else ("", [])
        rows = read_parquet(
            (base / "**" / "*.parquet").as_posix(),
            where=where,
            params=params,
            order_by="as_of, actor_id",
            columns=list(SCORE_SCHEMA),
        )
        return list(rows)
