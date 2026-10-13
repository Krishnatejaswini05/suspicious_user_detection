from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from riskdetect.adapters import read_records
from riskdetect.adapters.readers import read_parquet, source_files


def test_csv_rows_with_positions_and_empty_as_none(tmp_path: Path) -> None:
    path = tmp_path / "export.csv"
    path.write_text("user,action,note\nS42,post,\nU17,vote,hi\n", encoding="utf-8")
    records = list(read_records(path, "csv"))
    assert [r.position for r in records] == ["export.csv#1", "export.csv#2"]
    assert records[0].data == {"user": "S42", "action": "post", "note": None}


def test_jsonl_skips_blank_lines_and_flags_bad_ones(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"user": "S42"}\n\n{broken\n[1, 2]\n', encoding="utf-8")
    records = list(read_records(path, "jsonl"))
    assert records[0].data == {"user": "S42"}
    assert records[0].error is None
    assert records[1].position == "events.jsonl#3"
    assert records[1].error is not None and "invalid JSON" in records[1].error
    assert records[2].error == "JSON line is not an object"


def test_parquet_rows_across_batches(tmp_path: Path) -> None:
    path = tmp_path / "events.parquet"
    pq.write_table(pa.table({"user": ["a", "b", "c"], "n": [1, 2, 3]}), path)

    records = list(read_parquet(path, batch_size=2))
    assert [r.position for r in records] == [
        "events.parquet#1",
        "events.parquet#2",
        "events.parquet#3",
    ]
    assert records[2].data == {"user": "c", "n": 3}


def test_folder_reads_matching_files_in_name_order(tmp_path: Path) -> None:
    (tmp_path / "b.csv").write_text("x\n2\n", encoding="utf-8")
    (tmp_path / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    assert [p.name for p in source_files(tmp_path, "csv")] == ["a.csv", "b.csv"]
    assert [r.data["x"] for r in read_records(tmp_path, "csv")] == ["1", "2"]


def test_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(read_records(tmp_path / "missing.csv", "csv"))
