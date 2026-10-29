import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from riskdetect.storage.parquet import (
    TIMESTAMPTZ,
    describe,
    from_micros,
    infer_schema,
    read_all,
    read_parquet,
    to_micros,
    write_parquet,
)

T0 = datetime(2026, 8, 12, 3, 14, 7, 123456, tzinfo=UTC)
SCHEMA = {
    "id": "VARCHAR",
    "at": TIMESTAMPTZ,
    "domains": "VARCHAR[]",
    "fingerprint": "UBIGINT",
    "score": "DOUBLE",
    "flag": "BOOLEAN",
}


def test_round_trip_keeps_every_type(tmp_path: Path) -> None:
    rows: list[dict[str, Any]] = [
        {
            "id": "a",
            "at": T0,
            "domains": ["bit.ly", "x.com"],
            "fingerprint": 2**64 - 1,
            "score": 0.5,
            "flag": True,
        },
        {"id": "b", "at": None, "domains": None, "fingerprint": None, "score": None, "flag": None},
    ]
    path = tmp_path / "t.parquet"
    assert write_parquet(path, rows, SCHEMA) == 2
    assert read_all(path) == rows
    assert describe(path)["at"] == "TIMESTAMP WITH TIME ZONE"  # a real UTC timestamp on disk


def test_microsecond_precision(tmp_path: Path) -> None:
    assert from_micros(to_micros(T0)) == T0
    path = tmp_path / "t.parquet"
    write_parquet(path, [{"at": T0 + timedelta(microseconds=1)}], {"at": TIMESTAMPTZ})
    assert read_all(path)[0]["at"] == T0 + timedelta(microseconds=1)


def test_empty_file_keeps_its_columns(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"
    assert write_parquet(path, [], SCHEMA) == 0
    assert read_all(path) == []
    assert list(describe(path)) == list(SCHEMA)


def test_writing_replaces_the_file(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    write_parquet(path, [{"id": "a"}], {"id": "VARCHAR"})
    write_parquet(path, [{"id": "b"}], {"id": "VARCHAR"})
    assert read_all(path) == [{"id": "b"}]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["t.parquet"]  # no leftovers


def test_filtering_and_ordering(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    rows = [{"id": i, "seen": T0 + timedelta(minutes=m)} for i, m in (("x", 2), ("y", 0), ("z", 1))]
    write_parquet(path, rows, {"id": "VARCHAR", "seen": TIMESTAMPTZ})
    cutoff = to_micros(T0 + timedelta(minutes=2))
    found = read_parquet(path, where="epoch_us(seen) < ?", params=[cutoff], order_by="seen")
    assert [r["id"] for r in found] == ["y", "z"]


def test_schema_inference() -> None:
    rows: list[dict[str, Any]] = [
        {"n": 1, "x": 1.5, "s": "a", "t": T0, "l": ["a"], "b": True, "empty": None},
        {"n": 2, "x": 2, "s": None, "t": None, "l": None, "b": False, "empty": None},
    ]
    assert infer_schema(rows) == {
        "n": "BIGINT",
        "x": "DOUBLE",
        "s": "VARCHAR",
        "t": TIMESTAMPTZ,
        "l": "VARCHAR[]",
        "b": "BOOLEAN",
        "empty": "VARCHAR",
    }


def test_pyarrow_is_not_needed() -> None:
    assert "pyarrow" not in sys.modules


def test_files_from_before_a_column_existed_read_it_as_none(tmp_path: Path) -> None:
    old = {"id": "VARCHAR", "score": "DOUBLE"}
    new = {**old, "price": "DOUBLE"}
    write_parquet(tmp_path / "a.parquet", [{"id": "old", "score": 1.0}], old)
    write_parquet(tmp_path / "b.parquet", [{"id": "new", "score": 2.0, "price": 9.5}], new)
    rows = list(
        read_parquet((tmp_path / "*.parquet").as_posix(), columns=["id", "price"], order_by="id")
    )
    assert rows == [{"id": "new", "price": 9.5}, {"id": "old", "price": None}]
    only_old = list(read_parquet(tmp_path / "a.parquet", columns=["id", "price"]))
    assert only_old == [{"id": "old", "price": None}]
