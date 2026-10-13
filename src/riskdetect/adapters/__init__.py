"""Translate each platform's raw data into canonical Events, configured by YAML."""

from riskdetect.adapters.base import AdapterResult, PlatformAdapter, run_adapter
from riskdetect.adapters.config_loader import (
    EventMapping,
    PlatformConfig,
    PlatformConfigError,
    load_platform_config,
    parse_platform_config,
)
from riskdetect.adapters.generic import GenericAdapter
from riskdetect.adapters.readers import RawRecord, read_records
from riskdetect.adapters.registry import (
    DEFAULT_CONFIG_DIR,
    available_platforms,
    load_adapter,
    register_custom_adapter,
)
from riskdetect.adapters.report import MappingReport

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "AdapterResult",
    "EventMapping",
    "GenericAdapter",
    "MappingReport",
    "PlatformAdapter",
    "PlatformConfig",
    "PlatformConfigError",
    "RawRecord",
    "available_platforms",
    "load_adapter",
    "load_platform_config",
    "parse_platform_config",
    "read_records",
    "register_custom_adapter",
    "run_adapter",
]
