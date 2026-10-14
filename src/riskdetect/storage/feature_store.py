"""Offline feature store: snapshot tables of features per platform, as Parquet.

Layout: ``features/platform=<platform>/<name>.parquet``. Writing a table replaces
the previous one with the same name, so reruns don't accumulate stale rows.
The online store (latest values per actor, for realtime) comes with realtime/.
"""

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


class ParquetFeatureStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, platform: str, name: str = "snapshots") -> Path:
        return self.directory / f"platform={platform}" / f"{name}.parquet"

    def write(self, platform: str, rows: list[dict[str, Any]], name: str = "snapshots") -> Path:
        path = self.path(platform, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path)
        return path

    def read(self, platform: str, name: str = "snapshots") -> list[dict[str, Any]]:
        path = self.path(platform, name)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = pq.read_table(path).to_pylist()
        return rows
