"""Offline feature store: snapshot tables of features per platform, as Parquet.

Layout: ``features/platform=<platform>/<name>.parquet``. Writing a table replaces
the previous one with the same name, so reruns don't accumulate stale rows.
The online store (latest values per actor, for realtime) comes with realtime/.
"""

from pathlib import Path
from typing import Any

from riskdetect.storage.parquet import read_all, write_parquet


class ParquetFeatureStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, platform: str, name: str = "snapshots") -> Path:
        return self.directory / f"platform={platform}" / f"{name}.parquet"

    def write(self, platform: str, rows: list[dict[str, Any]], name: str = "snapshots") -> Path:
        path = self.path(platform, name)
        write_parquet(path, rows)
        return path

    def read(self, platform: str, name: str = "snapshots") -> list[dict[str, Any]]:
        path = self.path(platform, name)
        return read_all(path) if path.exists() else []
