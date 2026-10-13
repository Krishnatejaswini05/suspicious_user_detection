"""Load a platform end to end: raw files -> adapter -> ingestion -> storage."""

from pathlib import Path

from riskdetect.adapters import DEFAULT_CONFIG_DIR, MappingReport, load_adapter, run_adapter
from riskdetect.ingestion.pipeline import IngestionPipeline
from riskdetect.ingestion.publisher import Publisher
from riskdetect.ingestion.report import IngestReport
from riskdetect.storage import DataPaths, ParquetEventStore, ParquetQuarantineStore


def default_pipeline(paths: DataPaths, publisher: Publisher | None = None) -> IngestionPipeline:
    return IngestionPipeline(
        ParquetEventStore(paths.events), ParquetQuarantineStore(paths.quarantine), publisher
    )


def ingest_platform(
    platform: str,
    *,
    pipeline: IngestionPipeline,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    base_dir: Path | None = None,
) -> tuple[MappingReport, IngestReport]:
    """Translate a platform's raw files and ingest the results. Safe to repeat."""
    adapter = load_adapter(platform, config_dir=config_dir, base_dir=base_dir)
    mapping = adapter.new_report()
    ingest = pipeline.ingest(platform, run_adapter(adapter, mapping))
    return mapping, ingest
