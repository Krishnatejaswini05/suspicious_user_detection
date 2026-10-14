"""Event store v1: Parquet files on disk, queried with DuckDB.

Layout: ``events/platform=<platform>/date=<YYYY-MM-DD>/part-<id>.parquet``, where
the date is the event's occurred_at date in UTC. Each append writes new part
files and never rewrites old ones, except ``delete_actor`` for privacy requests.

Only storage/ knows about DuckDB and Parquet; everything else uses the
``EventStore`` interface.
"""

from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from riskdetect.schema import Event
from riskdetect.storage.parquet import (
    connect,
    from_micros,
    read_parquet,
    sql_path,
    sql_string,
    stage_rows,
    staged_select,
    to_micros,
    write_partitioned,
)
from riskdetect.storage.serialization import (
    EVENT_COLUMNS,
    EVENT_SCHEMA,
    event_to_row,
    row_to_event,
)

# On disk each file also carries its partition date, used for the date=<YYYY-MM-DD> folders.
_FILE_SCHEMA = {**EVENT_SCHEMA, "date": "VARCHAR"}


class ParquetEventStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._con = connect()

    # -- writing -------------------------------------------------------------

    def append(self, events: list[Event]) -> int:
        rows = [{**event_to_row(e), "date": e.occurred_at.date().isoformat()} for e in events]
        # A single write fills every platform/day folder, however many days the events span.
        return write_partitioned(
            self.directory, rows, _FILE_SCHEMA, ("platform", "date"), self._con
        )

    def delete_actor(self, platform: str, actor_id: str) -> int:
        removed = 0
        actor = sql_string(actor_id)
        for file in self._files(platform):
            row = self._con.execute(
                f"SELECT count(*) FILTER (WHERE actor_id = {actor}), count(*) "
                f"FROM read_parquet({sql_path(file)})"
            ).fetchone()
            matching, total = (int(row[0]), int(row[1])) if row else (0, 0)
            if not matching:
                continue
            removed += matching
            if matching == total:
                file.unlink()
                continue
            rewritten = file.with_name(file.name + ".rewrite")
            self._con.execute(
                f"COPY (SELECT * FROM read_parquet({sql_path(file)}) WHERE actor_id <> {actor}) "
                f"TO {sql_path(rewritten)} (FORMAT parquet)"
            )
            rewritten.replace(file)
        return removed

    # -- reading -------------------------------------------------------------

    def exists(self, event_ids: Iterable[str]) -> set[str]:
        ids = list(dict.fromkeys(event_ids))
        source = self._glob()
        if not ids or source is None:
            return set()
        # The IDs go to DuckDB as a staged file: passing a large list as a query
        # parameter is far slower (seconds for a few thousand IDs).
        id_schema = {"event_id": "VARCHAR"}
        staging = stage_rows([{"event_id": i} for i in ids], id_schema)
        try:
            rows = self._con.execute(
                f"SELECT DISTINCT e.event_id FROM read_parquet({sql_path(source)}, "
                f"hive_partitioning = false) e "
                f"JOIN ({staged_select(staging, id_schema)}) w USING (event_id)"
            ).fetchall()
        finally:
            staging.unlink(missing_ok=True)
        return {row[0] for row in rows}

    def get_actor_events(
        self,
        platform: str,
        actor_id: str,
        *,
        until: datetime | None = None,
        since: datetime | None = None,
    ) -> list[Event]:
        return list(self._query(platform, ["actor_id = ?"], [actor_id], start=since, end=until))

    def iter_events(
        self,
        platform: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator[Event]:
        return self._query(platform, [], [], start=start, end=end)

    def count(self, platform: str | None = None) -> int:
        source = self._glob(platform)
        if source is None:
            return 0
        row = self._con.execute(
            f"SELECT count(*) FROM read_parquet({sql_path(source)}, hive_partitioning = false)"
        ).fetchone()
        return int(row[0]) if row else 0

    def max_occurred_at(self, platform: str) -> datetime | None:
        source = self._glob(platform)
        if source is None:
            return None
        row = self._con.execute(
            f"SELECT epoch_us(max(occurred_at)) FROM read_parquet({sql_path(source)}, "
            "hive_partitioning = false)"
        ).fetchone()
        return from_micros(row[0]) if row and row[0] is not None else None

    # -- internals -----------------------------------------------------------

    def _base(self, platform: str | None) -> Path:
        return self.directory / f"platform={platform}" if platform else self.directory

    def _files(self, platform: str | None = None) -> list[Path]:
        base = self._base(platform)
        return sorted(base.glob("**/*.parquet")) if base.is_dir() else []

    def _glob(self, platform: str | None = None) -> str | None:
        """A glob over the relevant files, or None if there are none yet."""
        if not self._files(platform):
            return None
        return (self._base(platform) / "**" / "*.parquet").as_posix()

    def _query(
        self,
        platform: str | None,
        conditions: list[str],
        params: list[Any],
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[Event]:
        source = self._glob(platform)
        if source is None:
            return iter(())
        if start is not None:
            conditions.append("epoch_us(occurred_at) >= ?")
            params.append(to_micros(start))
        if end is not None:
            conditions.append("epoch_us(occurred_at) < ?")
            params.append(to_micros(end))
        rows = read_parquet(
            source,
            where=" AND ".join(conditions),
            params=params,
            order_by="occurred_at, event_id",
            columns=EVENT_COLUMNS,
            con=self._con,
        )
        return (row_to_event(row) for row in rows)
