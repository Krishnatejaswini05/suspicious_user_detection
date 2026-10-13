"""Save a simulation: one raw file per platform, plus the hidden answer key.

Layout under the output folder (normally ``data/``):

    raw/synthetic_forum/events.jsonl
    raw/synthetic_chat/events.parquet
    raw/synthetic_market/events.csv
    labels/answer_key.parquet       <- the truth; only labels/ and evaluation/ read it
"""

import csv
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from riskdetect.schema import Label
from riskdetect.synthetic.generator import AnswerKeyEntry, SimulationResult
from riskdetect.synthetic.personas import PersonaName
from riskdetect.synthetic.platforms import PROFILES, PlatformProfile

ANSWER_KEY_PATH = Path("labels") / "answer_key.parquet"


def write_simulation(result: SimulationResult, out_dir: Path) -> dict[str, Path]:
    """Write every platform's raw file and the answer key. Returns what was written."""
    written: dict[str, Path] = {}
    for platform, rows in result.rows.items():
        profile = PROFILES[platform]
        folder = out_dir / "raw" / platform
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"events.{profile.output_format}"
        _WRITERS[profile.output_format](profile, rows, path)
        written[platform] = path

    key_path = out_dir / ANSWER_KEY_PATH
    key_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([_key_row(e) for e in result.answer_key]), key_path)
    written["answer_key"] = key_path
    return written


def read_answer_key(path: Path) -> list[AnswerKeyEntry]:
    entries = []
    for row in pq.read_table(path).to_pylist():
        persona = PersonaName(row.pop("persona"))
        row.pop("is_bad")
        entries.append(AnswerKeyEntry(Label.model_validate(row), persona))
    return entries


def _key_row(entry: AnswerKeyEntry) -> dict[str, Any]:
    label = entry.label
    return {
        "actor_id": label.actor_id,
        "platform": label.platform,
        "persona": str(entry.persona),
        "category": str(label.category),
        "is_bad": label.abuse_start is not None,
        "abuse_start": label.abuse_start,
        "decided_at": label.decided_at,
        "source": str(label.source),
        "confidence": label.confidence,
    }


def _write_csv(profile: PlatformProfile, rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=profile.columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(profile: PlatformProfile, rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_parquet(profile: PlatformProfile, rows: list[dict[str, Any]], path: Path) -> None:
    columns = {name: [row[name] for row in rows] for name in profile.columns}
    pq.write_table(pa.table(columns), path)


_WRITERS = {"csv": _write_csv, "jsonl": _write_jsonl, "parquet": _write_parquet}
