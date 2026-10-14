import csv
import json
from pathlib import Path

import yaml

from riskdetect.storage.parquet import describe, read_all
from riskdetect.synthetic import SimulationResult, read_answer_key, write_simulation
from riskdetect.synthetic.__main__ import main
from riskdetect.synthetic.platforms import PROFILES


def test_writes_each_platform_in_its_own_format(
    tiny_result: SimulationResult, tmp_path: Path
) -> None:
    written = write_simulation(tiny_result, tmp_path)
    forum = written["synthetic_forum"]
    assert forum == tmp_path / "raw" / "synthetic_forum" / "events.jsonl"
    lines = forum.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(tiny_result.rows["synthetic_forum"])
    assert json.loads(lines[0]) == tiny_result.rows["synthetic_forum"][0]

    chat = read_all(written["synthetic_chat"])
    assert chat == tiny_result.rows["synthetic_chat"]
    assert tuple(describe(written["synthetic_chat"])) == PROFILES["synthetic_chat"].columns

    with written["synthetic_market"].open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == PROFILES["synthetic_market"].columns
        assert sum(1 for _ in reader) == len(tiny_result.rows["synthetic_market"])


def test_answer_key_round_trip(tiny_result: SimulationResult, tmp_path: Path) -> None:
    written = write_simulation(tiny_result, tmp_path)
    assert written["answer_key"] == tmp_path / "labels" / "answer_key.parquet"
    assert read_answer_key(written["answer_key"]) == tiny_result.answer_key


def test_command_line(tmp_path: Path, capsys: object) -> None:
    scenario = tmp_path / "s.yaml"
    scenario.write_text(
        yaml.safe_dump(
            {
                "name": "cli",
                "seed": 3,
                "start": "2026-08-01T00:00:00Z",
                "duration_days": 2,
                "platforms": {"synthetic_market": 5},
                "persona_mix": {"normal": 1.0},
            }
        ),
        encoding="utf-8",
    )
    assert main(["--scenario", str(scenario), "--out", str(tmp_path / "data")]) == 0
    assert (tmp_path / "data" / "raw" / "synthetic_market" / "events.csv").exists()
    assert (tmp_path / "data" / "labels" / "answer_key.parquet").exists()
