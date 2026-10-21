"""Where data lives. The only package that knows about Parquet and DuckDB."""

from riskdetect.storage.event_store import ParquetEventStore
from riskdetect.storage.feature_store import ParquetFeatureStore
from riskdetect.storage.interfaces import EventStore, QuarantinedRecord, QuarantineStore
from riskdetect.storage.label_store import ParquetLabelStore
from riskdetect.storage.paths import DEFAULT_DATA_ROOT, DataPaths
from riskdetect.storage.quarantine_store import ParquetQuarantineStore
from riskdetect.storage.score_store import ParquetScoreStore
from riskdetect.storage.serialization import EVENT_SCHEMA, event_to_row, row_to_event

__all__ = [
    "DEFAULT_DATA_ROOT",
    "EVENT_SCHEMA",
    "DataPaths",
    "EventStore",
    "ParquetEventStore",
    "ParquetFeatureStore",
    "ParquetLabelStore",
    "ParquetQuarantineStore",
    "ParquetScoreStore",
    "QuarantineStore",
    "QuarantinedRecord",
    "event_to_row",
    "row_to_event",
]
