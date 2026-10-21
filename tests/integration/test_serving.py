"""The API end to end: a warmed-up service, live events in, scores and reviews out."""

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from conftest import TINY
from riskdetect.features.__main__ import main as features_main
from riskdetect.ingestion import default_pipeline, ingest_platform
from riskdetect.serving import ApiServer, BadRequest, DetectorService, NotFound, ServiceConfig
from riskdetect.storage import DataPaths, ParquetLabelStore
from riskdetect.synthetic import SimulationResult, write_simulation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = PROJECT_ROOT / "configs"
FORUM = "synthetic_forum"


@pytest.fixture(scope="module")
def data_root(tiny_result: SimulationResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("serving")
    write_simulation(tiny_result, root / "data")
    pipeline = default_pipeline(DataPaths(root / "data"))
    for platform in ("synthetic_forum", "synthetic_chat", "synthetic_market"):
        ingest_platform(
            platform, pipeline=pipeline, config_dir=CONFIGS / "platforms", base_dir=root
        )
    assert (
        features_main(["--data", str(root / "data"), "--config-dir", str(CONFIGS / "platforms")])
        == 0
    )
    return root / "data"


def make_service(data_root: Path) -> DetectorService:
    return DetectorService(
        ServiceConfig(
            data_root=data_root,
            config_dir=CONFIGS / "platforms",
            rules_path=CONFIGS / "rules.yaml",
            scoring_path=CONFIGS / "scoring.yaml",
            blocked_domains_path=CONFIGS / "lists" / "blocked_domains.txt",
        )
    )


@pytest.fixture(scope="module")
def service(data_root: Path) -> DetectorService:
    return make_service(data_root)


def burst(
    tiny_result: SimulationResult, actor: str = "newbot", n: int = 12
) -> list[dict[str, Any]]:
    """Raw forum records: a brand-new account posting the same ad every 10 seconds."""
    start = tiny_result.scenario.end + timedelta(hours=1)
    rows: list[dict[str, Any]] = [
        {"id": f"{actor}-signup", "author": actor, "kind": "signup", "ts": start.isoformat()}
    ]
    for i in range(n):
        rows.append(
            {
                "id": f"{actor}-p{i}",
                "author": actor,
                "kind": "submission",
                "ts": (start + timedelta(seconds=10 * (i + 1))).isoformat(),
                "subforum": "f/news",
                "body": "Cheap phones today only! visit bit.ly/zz9zz9",
                "lang": "en",
            }
        )
    return rows


class TestService:
    def test_live_events_flag_a_new_bot(
        self, service: DetectorService, tiny_result: SimulationResult
    ) -> None:
        reply = service.ingest(FORUM, burst(tiny_result))
        assert (reply["received"], reply["stored"], reply["duplicates"]) == (13, 13, 0)
        assert [f["actor_id"] for f in reply["flagged"]] == ["newbot"]
        risk = service.risk(FORUM, "newbot")
        assert risk["tier"] in ("REVIEW", "HIGH")
        assert risk["reasons"] and risk["recommended_actions"]

    def test_resent_records_are_duplicates(
        self, service: DetectorService, tiny_result: SimulationResult
    ) -> None:
        again = service.ingest(FORUM, burst(tiny_result))
        assert (again["stored"], again["duplicates"]) == (0, 13)

    def test_records_without_ids_dedupe_by_content(
        self, service: DetectorService, tiny_result: SimulationResult
    ) -> None:
        record = {k: v for k, v in burst(tiny_result, actor="noid", n=1)[1].items() if k != "id"}
        assert service.ingest(FORUM, [record])["stored"] == 1
        assert service.ingest(FORUM, [record])["duplicates"] == 1

    def test_rejections_are_explained(self, service: DetectorService) -> None:
        reply = service.ingest(
            FORUM, [{"id": "x1", "author": "u1", "kind": "teleport", "ts": "2026-08-08T00:00:00Z"}]
        )
        assert reply["rejected"] == {"unmapped_action": 1}
        assert "teleport" in reply["rejections"][0]["detail"]

    def test_queue_and_review(self, service: DetectorService, data_root: Path) -> None:
        queue = service.review_queue(FORUM)
        assert "newbot" in [item["actor_id"] for item in queue["items"]]
        saved = service.record_review(
            FORUM, "newbot", "spam", reviewer="ana", note="obvious ad bot"
        )
        assert saved["saved_as_label"]
        assert "newbot" not in [i["actor_id"] for i in service.review_queue(FORUM)["items"]]
        labels = ParquetLabelStore(DataPaths(data_root).labels / "reviews")
        assert [
            (lab.actor_id, str(lab.category), str(lab.source)) for lab in labels.read(FORUM)
        ] == [("newbot", "spam", "reviewer")]
        assert labels.audit_log(FORUM)[0]["reviewer"] == "ana"

    def test_history(self, service: DetectorService) -> None:
        history = service.history(FORUM, "newbot")
        assert history["scores"]
        assert history["scores"][-1]["tier"] in ("REVIEW", "HIGH")

    def test_errors(self, service: DetectorService) -> None:
        with pytest.raises(NotFound):
            service.risk("nowhere", "u1")
        with pytest.raises(NotFound):
            service.risk(FORUM, "never-seen")
        with pytest.raises(BadRequest):
            service.record_review(FORUM, "newbot", "guilty")
        with pytest.raises(BadRequest):
            service.ingest(FORUM, "not a list")
        with pytest.raises(BadRequest):
            service.review_queue(limit=0)

    def test_status(self, service: DetectorService) -> None:
        assert service.health()["status"] == "ok"
        assert "self_baseline" in service.health()["models"]
        platforms = {p["platform"]: p for p in service.platforms()["platforms"]}
        assert platforms[FORUM]["users_tracked"] > 0
        assert platforms[FORUM]["percentiles_loaded"]

    def test_reviews_survive_a_restart(self, data_root: Path) -> None:
        restarted = make_service(data_root)  # warm-up rebuilds summaries from storage
        assert restarted.risk(FORUM, "newbot")["actor_id"] == "newbot"
        assert "newbot" not in [i["actor_id"] for i in restarted.review_queue(FORUM)["items"]]


@pytest.fixture(scope="module")
def server(service: DetectorService) -> Iterator[str]:
    api = ApiServer(("127.0.0.1", 0), service, api_key="s3cret", quiet=True)
    thread = threading.Thread(target=api.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{api.server_address[1]}"
    api.shutdown()
    api.server_close()


def call(
    url: str, body: Any = None, key: str | None = "s3cret", raw: bytes | None = None
) -> tuple[int, Any]:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    if key is not None:
        request.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


class TestHttp:
    def test_health_and_auth(self, server: str) -> None:
        assert call(f"{server}/health") == (200, call(f"{server}/health")[1])
        status, body = call(f"{server}/health", key=None)
        assert status == 401 and "X-API-Key" in body["error"]
        assert call(f"{server}/health", key="wrong")[0] == 401

    def test_events_risk_and_review_over_http(
        self, server: str, tiny_result: SimulationResult
    ) -> None:
        status, reply = call(
            f"{server}/events", {"platform": FORUM, "records": burst(tiny_result, "httpbot")}
        )
        assert status == 200 and reply["stored"] == 13
        status, risk = call(f"{server}/actors/{FORUM}/httpbot/risk")
        assert status == 200 and risk["tier"] in ("REVIEW", "HIGH")
        status, queue = call(f"{server}/review-queue?platform={FORUM}&limit=5")
        assert status == 200 and queue["count"] >= 1
        status, saved = call(f"{server}/actors/{FORUM}/httpbot/review", {"decision": "clean"})
        assert status == 200 and saved["decision"] == "clean"
        assert call(f"{server}/actors/{FORUM}/httpbot/history")[0] == 200
        assert call(f"{server}/platforms")[0] == 200

    def test_bad_requests(self, server: str) -> None:
        assert call(f"{server}/nope")[0] == 404
        assert call(f"{server}/events", raw=b"{not json")[0] == 400
        assert call(f"{server}/events", {"records": []})[0] == 400
        assert call(f"{server}/review-queue?limit=abc")[0] == 400
        assert call(f"{server}/actors/{FORUM}/nobody/risk")[0] == 404


def test_queue_is_complete_right_after_a_restart(data_root: Path) -> None:
    # httpbot was reviewed as clean and newbot as spam earlier; a fresh bot is not.
    service = make_service(data_root)
    assert service.ingest(FORUM, burst_after_restart())["stored"] > 0
    restarted = make_service(data_root)
    assert "laterbot" in [item["actor_id"] for item in restarted.review_queue(FORUM)["items"]]


def burst_after_restart() -> list[dict[str, Any]]:
    rows = []
    start = TINY.end + timedelta(hours=2)
    for i in range(12):
        rows.append(
            {
                "id": f"laterbot-p{i}",
                "author": "laterbot",
                "kind": "submission",
                "ts": (start + timedelta(seconds=10 * i)).isoformat(),
                "subforum": "f/news",
                "body": "Cheap phones today only! visit bit.ly/zz9zz9",
            }
        )
    return rows
