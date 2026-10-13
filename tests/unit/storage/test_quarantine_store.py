from datetime import UTC, datetime
from pathlib import Path

from riskdetect.schema import Rejection, RejectionReason
from riskdetect.storage import ParquetQuarantineStore

T0 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def test_round_trip(tmp_path: Path) -> None:
    store = ParquetQuarantineStore(tmp_path / "quarantine")
    rejection = Rejection(
        RejectionReason.UNMAPPED_ACTION,
        "action='teleport' is not listed",
        ("action",),
        {"member_id": "u1", "action": "teleport", "price": 5},
    )
    assert store.append("synthetic_market", [rejection], T0) == 1
    assert store.append("synthetic_market", [], T0) == 0

    [record] = store.read("synthetic_market")
    assert record.platform == "synthetic_market"
    assert record.quarantined_at == T0
    assert record.rejection == rejection
    assert store.read("synthetic_forum") == []
    assert len(store.read()) == 1


def test_missing_raw(tmp_path: Path) -> None:
    store = ParquetQuarantineStore(tmp_path / "quarantine")
    store.append(
        "synthetic_chat", [Rejection(RejectionReason.INVALID_STRUCTURE, "bad", (), None)], T0
    )
    assert store.read()[0].rejection.raw is None
