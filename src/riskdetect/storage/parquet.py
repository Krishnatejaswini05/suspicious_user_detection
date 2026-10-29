"""Read and write Parquet files through DuckDB.

Every Parquet file in the project goes through this module. It deliberately
avoids PyArrow (blocked by an application-control policy on the development
machine), using DuckDB alone.

Timezone-aware timestamps travel between Python and DuckDB as epoch
microseconds: converting TIMESTAMPTZ values directly would need the pytz package.
On disk they are proper Parquet UTC timestamps, readable by any tool.
"""

import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

TIMESTAMPTZ = "TIMESTAMPTZ"
_TZ_TYPES = {"TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)
DEFAULT_BATCH_ROWS = 10_000

Schema = Mapping[str, str]  # column name -> DuckDB type, e.g. {"id": "VARCHAR", "at": TIMESTAMPTZ}
Row = dict[str, Any]


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("SET enable_progress_bar = false")
    return con


def to_micros(moment: datetime) -> int:
    return (moment - _EPOCH) // _MICROSECOND


def from_micros(micros: int) -> datetime:
    return _EPOCH + timedelta(microseconds=micros)


def sql_string(text: str) -> str:
    """A SQL string literal (for places DuckDB does not accept parameters, such as COPY)."""
    return "'" + text.replace("'", "''") + "'"


def sql_path(path: Path | str) -> str:
    return sql_string(path.as_posix() if isinstance(path, Path) else path)


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# -- schema inference ----------------------------------------------------------


def infer_schema(rows: Sequence[Row]) -> dict[str, str]:
    """Column types from the values present. Columns with no values become VARCHAR."""
    seen: dict[str, set[type]] = {}
    for row in rows:
        for name, value in row.items():
            kinds = seen.setdefault(name, set())
            if value is not None:
                kinds.add(type(value))
    return {name: _duck_type(kinds) for name, kinds in seen.items()}


def _duck_type(kinds: set[type]) -> str:
    if not kinds:
        return "VARCHAR"
    if kinds <= {bool}:
        return "BOOLEAN"
    if kinds <= {int, bool}:
        return "BIGINT"
    if kinds <= {int, float, bool}:
        return "DOUBLE"
    if kinds <= {datetime}:
        return TIMESTAMPTZ
    if kinds <= {list, tuple}:
        return "VARCHAR[]"
    return "VARCHAR"


# -- writing -------------------------------------------------------------------


def write_parquet(
    path: Path,
    rows: Iterable[Row],
    schema: Schema | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> int:
    """Write rows to one Parquet file (replacing it). Returns the number of rows written.

    Rows are staged as JSON lines, then DuckDB converts them; no extra libraries needed.
    """
    rows = list(rows)
    columns = dict(schema) if schema is not None else infer_schema(rows)
    con = con or connect()
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.with_name(path.name + ".writing")  # replace only once fully written

    if not rows:
        select = ", ".join(
            f"CAST(NULL AS {kind}) AS {_ident(name)}" for name, kind in columns.items()
        )
        con.execute(f"COPY (SELECT {select} WHERE false) TO {sql_path(target)} (FORMAT parquet)")
        os.replace(target, path)
        return 0

    staging = stage_rows(rows, columns)
    try:
        con.execute(
            f"COPY ({staged_select(staging, columns)}) TO {sql_path(target)} (FORMAT parquet)"
        )
        os.replace(target, path)
    finally:
        staging.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
    return len(rows)


def write_partitioned(
    directory: Path,
    rows: Iterable[Row],
    schema: Schema,
    partition_by: Sequence[str],
    con: duckdb.DuckDBPyConnection | None = None,
) -> int:
    """Add rows to a folder partitioned as ``<col>=<value>/...``, in a single write.

    Each call adds new uniquely named part files; existing files are never touched.
    Partition columns are also kept inside the files.
    """
    rows = list(rows)
    if not rows:
        return 0
    con = con or connect()
    directory.mkdir(parents=True, exist_ok=True)
    staging = stage_rows(rows, schema)
    partitions = ", ".join(_ident(name) for name in partition_by)
    try:
        con.execute(
            f"COPY ({staged_select(staging, schema)}) TO {sql_path(directory)} "
            f"(FORMAT parquet, PARTITION_BY ({partitions}), WRITE_PARTITION_COLUMNS true, "
            "FILENAME_PATTERN 'part-{uuid}', APPEND true)"
        )
    finally:
        staging.unlink(missing_ok=True)
    return len(rows)


def stage_rows(rows: list[Row], columns: Mapping[str, str]) -> Path:
    """Write rows as JSON lines in the system temp folder (short paths, flat memory)."""
    handle, name = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(_staged(row, columns), ensure_ascii=False) + "\n")
    return Path(name)


def staged_select(staging: Path, columns: Mapping[str, str]) -> str:
    """SQL that reads a staged file back with the right column types."""
    json_columns = ", ".join(
        f"{sql_string(name)}: {sql_string('BIGINT' if kind in _TZ_TYPES else kind)}"
        for name, kind in columns.items()
    )
    select = ", ".join(
        f"make_timestamp({_ident(name)})::TIMESTAMPTZ AS {_ident(name)}"
        if kind in _TZ_TYPES
        else _ident(name)
        for name, kind in columns.items()
    )
    return (
        f"SELECT {select} FROM read_json({sql_path(staging)}, "
        f"format = 'newline_delimited', columns = {{{json_columns}}})"
    )


def _staged(row: Row, columns: Mapping[str, str]) -> Row:
    staged: Row = {}
    for name, kind in columns.items():
        value = row.get(name)
        if value is not None and kind in _TZ_TYPES:
            value = to_micros(value)
        elif isinstance(value, tuple):
            value = list(value)
        staged[name] = value
    return staged


# -- reading -------------------------------------------------------------------


def describe(source: Path | str, con: duckdb.DuckDBPyConnection | None = None) -> dict[str, str]:
    """Column name -> DuckDB type for a Parquet file or glob."""
    con = con or connect()
    rows = con.execute(f"DESCRIBE SELECT * FROM {_scan(source)}").fetchall()
    return {str(name): str(kind) for name, kind, *_ in rows}


def read_parquet(
    source: Path | str,
    *,
    where: str = "",
    params: Sequence[Any] = (),
    order_by: str = "",
    columns: Sequence[str] | None = None,
    batch_rows: int = DEFAULT_BATCH_ROWS,
    con: duckdb.DuckDBPyConnection | None = None,
) -> Iterator[Row]:
    """Stream rows from a Parquet file or glob as dicts, with timestamps as aware UTC datetimes.

    ``where`` and ``order_by`` are SQL fragments over the file's columns; values go in
    ``params``. ``columns`` limits (and orders) the columns returned. Timezone-aware
    timestamp columns can be compared as epoch microseconds with ``epoch_us(column)``.

    Files written by older versions may lack newer columns: across a glob, columns are
    matched by name, and a requested column no file has is returned as None.
    """
    con = con or connect()
    present = describe(source, con)
    names = list(columns) if columns is not None else list(present)
    tz_columns = {name for name in names if present.get(name) in _TZ_TYPES}
    select = ", ".join(
        f"epoch_us({_ident(name)}) AS {_ident(name)}"
        if name in tz_columns
        else (_ident(name) if name in present else f"NULL AS {_ident(name)}")
        for name in names
    )
    query = f"SELECT {select} FROM {_scan(source)}"
    if where:
        query += f" WHERE {where}"
    if order_by:
        query += f" ORDER BY {order_by}"
    cursor = con.execute(query, list(params))
    while batch := cursor.fetchmany(batch_rows):
        for values in batch:
            row = dict(zip(names, values, strict=True))
            for name in tz_columns:
                if row[name] is not None:
                    row[name] = from_micros(row[name])
            yield row


def _scan(source: Path | str) -> str:
    return f"read_parquet({sql_path(source)}, hive_partitioning = false, union_by_name = true)"


def read_all(source: Path | str, con: duckdb.DuckDBPyConnection | None = None) -> list[Row]:
    return list(read_parquet(source, con=con))
