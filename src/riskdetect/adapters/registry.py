"""Find the adapter for a platform by name.

Every platform uses the generic adapter with its YAML file, unless a custom
adapter has been registered for it (only for sources YAML cannot describe).
"""

from collections.abc import Callable
from pathlib import Path

from riskdetect.adapters.base import PlatformAdapter
from riskdetect.adapters.config_loader import PlatformConfig, load_platform_config
from riskdetect.adapters.generic import GenericAdapter

DEFAULT_CONFIG_DIR = Path("configs/platforms")

CustomAdapterFactory = Callable[[PlatformConfig, Path], PlatformAdapter]
_CUSTOM_ADAPTERS: dict[str, CustomAdapterFactory] = {}


def register_custom_adapter(platform: str, factory: CustomAdapterFactory) -> None:
    """Use ``factory(config, base_dir)`` instead of the generic adapter for ``platform``."""
    _CUSTOM_ADAPTERS[platform] = factory


def available_platforms(config_dir: Path = DEFAULT_CONFIG_DIR) -> list[str]:
    """Platforms with a config file. Files starting with ``_`` (e.g. the template) are skipped."""
    if not config_dir.is_dir():
        return []
    return sorted(p.stem for p in config_dir.glob("*.yaml") if not p.stem.startswith("_"))


def load_adapter(
    platform: str,
    *,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    base_dir: Path | None = None,
) -> PlatformAdapter:
    config = load_platform_config(config_dir / f"{platform}.yaml")
    resolved_base = base_dir or Path.cwd()
    factory = _CUSTOM_ADAPTERS.get(platform)
    if factory is not None:
        return factory(config, resolved_base)
    return GenericAdapter(config, base_dir=resolved_base)
