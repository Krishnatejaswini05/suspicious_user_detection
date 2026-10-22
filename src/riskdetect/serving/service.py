"""The detector as a service: everything the API offers, independent of any web framework.

The HTTP layer (serving/http.py, Python's built-in server) only parses requests and
calls these methods; a FastAPI or other front end could wrap the same service.

On start, the live desk is warmed up from stored events, and every user active in the
last week is judged once, so scores and the review queue are complete before the first
request. All methods are safe to call from several threads.
"""

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from riskdetect.adapters import (
    DEFAULT_CONFIG_DIR,
    PlatformAdapter,
    RawRecord,
    available_platforms,
    load_adapter,
    load_platform_config,
)
from riskdetect.features import PercentileTable, fields_from_config
from riskdetect.ingestion import CallbackPublisher, IngestionPipeline
from riskdetect.models import load_models
from riskdetect.realtime import RealtimeProcessor, RescorePolicy
from riskdetect.rules import DEFAULT_RULES_PATH, load_rules
from riskdetect.rules.lists import DEFAULT_BLOCKED_DOMAINS_PATH, load_domain_list
from riskdetect.schema import Label, LabelCategory, LabelSource, Rejection
from riskdetect.scoring import DEFAULT_SCORING_PATH, RiskResult, Scorer, Tier, load_scoring_config
from riskdetect.storage import (
    DEFAULT_DATA_ROOT,
    DataPaths,
    ParquetEventStore,
    ParquetFeatureStore,
    ParquetLabelStore,
    ParquetQuarantineStore,
    ParquetScoreStore,
)

REVIEWER_CONFIDENCE = 0.9  # a careful human decision, but not infallible
_RECENT = timedelta(days=7)  # users active this recently are judged again on start
_JUST_AFTER = timedelta(microseconds=1)
_TIER_RANK = {Tier.LOW: 0, Tier.WATCH: 1, Tier.REVIEW: 2, Tier.HIGH: 3}
_MAX_RECORDS_PER_REQUEST = 10_000


class ServiceError(Exception):
    status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequest(ServiceError):
    status = 400


class NotFound(ServiceError):
    status = 404


@dataclass(frozen=True)
class ServiceConfig:
    data_root: Path = DEFAULT_DATA_ROOT
    config_dir: Path = DEFAULT_CONFIG_DIR
    rules_path: Path = DEFAULT_RULES_PATH
    scoring_path: Path = DEFAULT_SCORING_PATH
    blocked_domains_path: Path = DEFAULT_BLOCKED_DOMAINS_PATH
    policy: RescorePolicy = field(default_factory=RescorePolicy)
    platforms: tuple[str, ...] | None = None  # only these platforms; None = every config file


def result_to_api(result: RiskResult) -> dict[str, Any]:
    """A JSON-ready view of a score, for API responses."""
    return {
        "platform": result.platform,
        "actor_id": result.actor_id,
        "as_of": result.as_of.isoformat(),
        "score": result.score,
        "tier": str(result.tier),
        "confidence": str(result.confidence),
        "categories": result.categories,
        "reasons": [{"code": r.code, "text": r.text} for r in result.reasons],
        "recommended_actions": list(result.actions),
        "rules_fired": list(result.rules_fired),
        "signals": list(result.signals),
        "versions": {"rules": result.rules_version, "scoring": result.scoring_version},
    }


def _record_position(record: dict[str, Any]) -> str:
    """A stable "position" for a record sent over the API, from its own contents.

    Files give each row a position (``file.csv#12``) that derived event IDs use. API
    records have none, so their contents stand in: a resent record gets the same ID and
    is recognized as a duplicate. Platforms should still send their own event IDs.
    """
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()
    return f"api#{digest[:24]}"


class DetectorService:
    def __init__(
        self,
        config: ServiceConfig | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        warm_up: bool = True,
    ) -> None:
        self.config = config or ServiceConfig()
        self.clock = clock
        paths = DataPaths(self.config.data_root)
        self.events = ParquetEventStore(paths.events)
        self.scores = ParquetScoreStore(paths.scores)
        self.labels = ParquetLabelStore(paths.labels / "reviews")
        features = ParquetFeatureStore(paths.features)

        names = available_platforms(self.config.config_dir)
        if self.config.platforms is not None:
            unknown = set(self.config.platforms) - set(names)
            if unknown:
                raise ValueError(f"unknown platforms {sorted(unknown)}; known: {names}")
            names = [name for name in names if name in self.config.platforms]
        self.adapters: dict[str, PlatformAdapter] = {
            name: load_adapter(name, config_dir=self.config.config_dir) for name in names
        }
        fields = {
            name: fields_from_config(load_platform_config(self.config.config_dir / f"{name}.yaml"))
            for name in names
        }
        percentiles = {}
        for name in names:
            path = features.path(name, "percentiles").with_suffix(".json")
            if path.exists():
                percentiles[name] = PercentileTable.load(path)

        self.scorer = Scorer(
            load_rules(self.config.rules_path),
            load_scoring_config(self.config.scoring_path),
            models=load_models(paths.root / "models"),
        )
        self._new_results: list[RiskResult] = []
        self.processor = RealtimeProcessor(
            self.scorer,
            percentiles=percentiles,
            available_fields=fields,
            blocked_domains=load_domain_list(self.config.blocked_domains_path),
            policy=self.config.policy,
            on_result=self._new_results.append,
        )
        self.pipeline = IngestionPipeline(
            self.events,
            ParquetQuarantineStore(paths.quarantine),
            CallbackPublisher(self.processor.on_events),
            clock=clock,
        )
        self._reviewed: dict[tuple[str, str], datetime] = {
            (label.platform, label.actor_id): label.decided_at for label in self.labels.read()
        }
        self._lock = threading.Lock()
        if warm_up:
            for name in names:
                self.processor.warm_up(self.events, name)
            self._judge_recent_users()

    # -- sending data ----------------------------------------------------------------

    def ingest(self, platform: str, records: Any) -> dict[str, Any]:
        """Translate and store a platform's raw records, scoring users live as they act."""
        adapter = self._adapter(platform)
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            raise BadRequest("'records' must be a list of objects")
        if len(records) > _MAX_RECORDS_PER_REQUEST:
            raise BadRequest(f"at most {_MAX_RECORDS_PER_REQUEST} records per request")
        with self._lock:
            results = []
            for record in records:
                results.extend(adapter.to_events(RawRecord(_record_position(record), record)))
            report = self.pipeline.ingest(platform, results)
            new = self._drain()
        escalated = [result_to_api(r) for r in new if r.tier in (Tier.REVIEW, Tier.HIGH)]
        return {
            "platform": platform,
            "received": report.received,
            "stored": report.stored,
            "duplicates": report.duplicates,
            "rejected": {str(reason): n for reason, n in report.rejections.items()},
            "rejections": [
                {"reason": str(r.reason), "detail": r.detail}
                for r in results
                if isinstance(r, Rejection)
            ][:20],
            "scored": len(new),
            "flagged": escalated,
        }

    # -- asking ----------------------------------------------------------------------

    def risk(self, platform: str, actor_id: str) -> dict[str, Any]:
        self._adapter(platform)
        with self._lock:
            result = self.processor.latest.get((platform, actor_id))
            if result is None:
                result = self.processor.score_now(platform, actor_id)
                self._drain()
        if result is None:
            raise NotFound(f"no activity known for {actor_id!r} on {platform!r}")
        return result_to_api(result)

    def history(self, platform: str, actor_id: str) -> dict[str, Any]:
        """A user's scores over time: live scores, or else the daily batch scores."""
        self._adapter(platform)
        rows = self.scores.read_history(platform, actor_id=actor_id)
        source = "live"
        if not rows:
            rows = self.scores.read_actor(platform, actor_id)
            source = "daily"
        if not rows:
            raise NotFound(f"no scores recorded for {actor_id!r} on {platform!r}")
        return {
            "platform": platform,
            "actor_id": actor_id,
            "source": source,
            "scores": [
                {
                    "as_of": row["as_of"].isoformat(),
                    "score": row["score"],
                    "tier": row["tier"],
                    "reasons": row["reasons"] or [],
                }
                for row in rows
            ],
        }

    def review_queue(self, platform: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Users a person should check (REVIEW and HIGH, not reviewed since), most urgent first."""
        if platform is not None:
            self._adapter(platform)
        if limit < 1:
            raise BadRequest("limit must be at least 1")
        with self._lock:
            waiting = [
                result
                for (p, actor), result in self.processor.latest.items()
                if result.tier in (Tier.REVIEW, Tier.HIGH)
                and (platform is None or p == platform)
                and self._reviewed.get((p, actor), datetime.min.replace(tzinfo=UTC)) < result.as_of
            ]
        waiting.sort(key=lambda r: (-_TIER_RANK[r.tier], -r.score, r.platform, r.actor_id))
        return {"count": len(waiting), "items": [result_to_api(r) for r in waiting[:limit]]}

    # -- reviewers' decisions ----------------------------------------------------------

    def record_review(
        self,
        platform: str,
        actor_id: str,
        decision: Any,
        reviewer: Any = None,
        note: Any = None,
    ) -> dict[str, Any]:
        """Save a reviewer's verdict as a label, for future training."""
        self._adapter(platform)
        categories = {c.value for c in LabelCategory}
        if decision not in categories:
            raise BadRequest(f"decision must be one of {sorted(categories)}")
        with self._lock:
            known = (platform, actor_id) in self.processor.latest or actor_id in (
                self.processor.engines[platform].states
                if platform in self.processor.engines
                else {}
            )
            if not known:
                raise NotFound(f"no activity known for {actor_id!r} on {platform!r}")
            now = self.clock()
            label = Label(
                actor_id=actor_id,
                platform=platform,
                category=LabelCategory(decision),
                decided_at=now,
                source=LabelSource.REVIEWER,
                confidence=REVIEWER_CONFIDENCE,
            )
            audit = {
                "reviewer": None if reviewer is None else str(reviewer),
                "note": None if note is None else str(note)[:1000],
            }
            self.labels.append([label], extra=[audit])
            self._reviewed[(platform, actor_id)] = now
        return {
            "platform": platform,
            "actor_id": actor_id,
            "decision": decision,
            "decided_at": now.isoformat(),
            "saved_as_label": True,
        }

    # -- status ----------------------------------------------------------------------

    def platforms(self) -> dict[str, Any]:
        with self._lock:
            tracked = {p: len(e.states) for p, e in self.processor.engines.items()}
        return {
            "platforms": [
                {
                    "platform": name,
                    "users_tracked": tracked.get(name, 0),
                    "percentiles_loaded": name in self.processor.percentiles,
                }
                for name in sorted(self.adapters)
            ]
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "rules_version": self.scorer.rules.version,
            "scoring_version": self.scorer.config.version,
            "tiers": self.scorer.config.tiers.model_dump(),
            "models": [model.name for model in self.scorer.models],
            "platforms": sorted(self.adapters),
        }

    # -- internals ---------------------------------------------------------------------

    def _adapter(self, platform: str) -> PlatformAdapter:
        adapter = self.adapters.get(platform)
        if adapter is None:
            raise NotFound(f"unknown platform {platform!r}; known: {sorted(self.adapters)}")
        return adapter

    def _judge_recent_users(self) -> None:
        """Score everyone active in the last week once, so the queue is complete after a restart.

        These catch-up scores repeat what history already holds, so they are not stored again.
        """
        for platform, engine in self.processor.engines.items():
            now = self.processor.latest_time(platform)
            if now is None:
                continue
            for actor in engine.active_actors(now + _JUST_AFTER, now - _RECENT):
                self.processor.score_now(platform, actor)
        self._new_results.clear()

    def _drain(self) -> list[RiskResult]:
        """Take the scores produced since the last call and record them as history."""
        new = list(self._new_results)
        self._new_results.clear()
        if new:
            self.scores.append_history([r.to_row() for r in new])
        return new
