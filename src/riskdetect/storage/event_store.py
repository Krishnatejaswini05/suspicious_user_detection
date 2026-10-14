"""Event store v1: Parquet files on disk, queried with DuckDB.

Layout: ``events/platform=<platform>/date=<YYYY-MM-DD>/part-<id>.parquet``, where
the date is the event's occurred_at date in UTC. Each append writes new part
files and never rewrites old ones, except ``delete_actor`` for privacy requests.

Only this module knows about DuckDB and Parquet; everything else uses the
``EventStore`` interface.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from riskdetect.schema import Event
from riskdetect.storage.serialization import EVENT_COLUMNS, events_to_table, row_to_event

_READ_BATCH_ROWS = 10_000


class ParquetEventStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._con = duckdb.connect()
        self._con.execute("SET TimeZone = 'UTC'")  # timestamps come back in UTC
        self._con.execute("SET enable_progress_bar = false")

    # -- writing -------------------------------------------------------------

    def append(self, events: list[Event]) -> int:
        groups: dict[tuple[str, str], list[Event]] = defaultdict(list)
        for event in events:
            groups[(event.platform, event.occurred_at.date().isoformat())].append(event)
        for (platform, day), group in groups.items():
            folder = self.directory / f"platform={platform}" / f"date={day}"
            folder.mkdir(parents=True, exist_ok=True)
            name = f"part-{uuid.uuid4().hex[:16]}.parquet"  # short: Windows limits path length
            pq.write_table(events_to_table(group), folder / name)
        return len(events)

    def delete_actor(self, platform: str, actor_id: str) -> int:
        removed = 0
        for file in self._files(platform):
            table = pq.read_table(file)
            keep = pc.not_equal(table["actor_id"], actor_id)
            kept = table.filter(keep)
            if kept.num_rows == table.num_rows:
                continue
            removed += table.num_rows - kept.num_rows
            if kept.num_rows:
                pq.write_table(kept, file)
            else:
                file.unlink()
        return removed

    # -- reading -------------------------------------------------------------

    def exists(self, event_ids: Iterable[str]) -> set[str]:
        ids = list(dict.fromkeys(event_ids))
        source = self._source()
        if not ids or source is None:
            return set()
        self._con.register("_wanted", pa.table({"event_id": ids}))
        try:
            rows = self._con.execute(
                f"SELECT DISTINCT e.event_id FROM {source} e JOIN _wanted w USING (event_id)"
            ).fetchall()
        finally:
            self._con.unregister("_wanted")
        return {row[0] for row in rows}

    def get_actor_events(
        self,
        platform: str,
        actor_id: str,
        *,
        until: datetime | None = None,
        since: datetime | None = None,
    ) -> list[Event]:
        conditions, params = ["actor_id = ?"], [actor_id]
        return list(self._query(platform, conditions, params, start=since, end=until))

    def iter_events(
        self,
        platform: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator[Event]:
        return self._query(platform, [], [], start=start, end=end)

    def count(self, platform: str | None = None) -> int:
        source = self._source(platform)
        if source is None:
            return 0
        row = self._con.execute(f"SELECT count(*) FROM {source}").fetchone()
        return int(row[0]) if row else 0

    def max_occurred_at(self, platform: str) -> datetime | None:
        source = self._source(platform)
        if source is None:
            return None
        # Fetched as epoch microseconds: converting TIMESTAMPTZ directly would need pytz.
        row = self._con.execute(f"SELECT epoch_us(max(occurred_at)) FROM {source}").fetchone()
        if not row or row[0] is None:
            return None
        return datetime.fromtimestamp(0, UTC) + timedelta(microseconds=row[0])

    # -- internals -----------------------------------------------------------

    def _files(self, platform: str | None = None) -> list[Path]:
        base = self.directory / f"platform={platform}" if platform else self.directory
        return sorted(base.glob("**/*.parquet")) if base.is_dir() else []

    def _source(self, platform: str | None = None) -> str | None:
        """A DuckDB table expression over the relevant files, or None if there are none."""
        if not self._files(platform):
            return None
        base = self.directory / f"platform={platform}" if platform else self.directory
        pattern = (base / "**" / "*.parquet").as_posix().replace("'", "''")
        columns = ", ".join(EVENT_COLUMNS)  # excludes the date= partition folder name
        return f"(SELECT {columns} FROM read_parquet('{pattern}', hive_partitioning = false))"

    def _query(
        self,
        platform: str | None,
        conditions: list[str],
        params: list[Any],
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[Event]:
        source = self._source(platform)
        if source is None:
            return iter(())
        if start is not None:
            conditions.append("occurred_at >= ?")
            params.append(start)
        if end is not None:
            conditions.append("occurred_at < ?")
            params.append(end)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        reader = self._con.execute(
            f"SELECT * FROM {source} {where} ORDER BY occurred_at, event_id", params
        ).to_arrow_reader(_READ_BATCH_ROWS)
        return (row_to_event(row) for batch in reader for row in batch.to_pylist())
