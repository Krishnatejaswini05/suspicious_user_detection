"""Where each kind of data lives on disk. One place, so no folder name is repeated."""

from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_ROOT = Path("data")


@dataclass(frozen=True)
class DataPaths:
    root: Path = DEFAULT_DATA_ROOT

    @property
    def raw(self) -> Path:
        """Input files exactly as platforms (or the simulator) delivered them."""
        return self.root / "raw"

    @property
    def events(self) -> Path:
        """Canonical events, partitioned as events/platform=<p>/date=<YYYY-MM-DD>/."""
        return self.root / "events"

    @property
    def quarantine(self) -> Path:
        """Rejected records with their reasons, for repair and reload."""
        return self.root / "quarantine"

    @property
    def labels(self) -> Path:
        return self.root / "labels"

    @property
    def features(self) -> Path:
        return self.root / "features"

    @property
    def scores(self) -> Path:
        return self.root / "scores"
