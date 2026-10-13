"""Read raw records from CSV, JSON-lines or Parquet files, without interpreting them.

Each record carries its position in the source (``"file.csv#12"``). Positions use
the file name, not the full path, so moving the data folder does not change
derived event IDs.
"""

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from riskdetect.adapters.config_loader import SourceFormat

_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "csv": (".csv",),
    "jsonl": (".jsonl", ".ndjson"),
    "parquet": (".parquet",),
}
PARQUET_BATCH_SIZE = 10_000


@dataclass(frozen=True, slots=True)
class RawRecord:
    """One raw row. ``error`` is set when the row itself could not be read."""

    position: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def source_files(path: Path, fmt: SourceFormat) -> list[Path]:
    """The files to read: ``path`` itself, or every matching file in that folder."""
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.suffix.lower() in _EXTENSIONS[fmt])
    raise FileNotFoundError(f"Source not found: {path}")


def read_csv(path: Path) -> Iterator[RawRecord]:
    with path.open(newline="", encoding="utf-8") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=1):
            data = {key: (value if value != "" else None) for key, value in row.items()}
            yield RawRecord(f"{path.name}#{row_number}", data)


def read_jsonl(path: Path) -> Iterator[RawRecord]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            position = f"{path.name}#{line_number}"
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                yield RawRecord(position, error=f"invalid JSON: {exc.msg}")
                continue
            if not isinstance(data, dict):
                yield RawRecord(position, error="JSON line is not an object")
                continue
            yield RawRecord(position, data)


def read_parquet(path: Path, batch_size: int = PARQUET_BATCH_SIZE) -> Iterator[RawRecord]:
    row_number = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
        for data in batch.to_pylist():
            row_number += 1
            yield RawRecord(f"{path.name}#{row_number}", data)


_READERS = {"csv": read_csv, "jsonl": read_jsonl, "parquet": read_parquet}


def read_records(path: Path, fmt: SourceFormat) -> Iterator[RawRecord]:
    """Stream records from one file or a folder of files, in file-name order."""
    reader = _READERS[fmt]
    for file in source_files(path, fmt):
        yield from reader(file)
