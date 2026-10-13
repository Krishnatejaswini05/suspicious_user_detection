from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from riskdetect.adapters import (
    GenericAdapter,
    MappingReport,
    PlatformConfig,
    PlatformConfigError,
    RawRecord,
    available_platforms,
    load_adapter,
    register_custom_adapter,
)
from riskdetect.adapters import registry as registry_module
from riskdetect.schema import Event, Rejection

CONFIG = {
    "platform": "mini_forum",
    "source": {"format": "jsonl", "path": "raw/forum.jsonl"},
    "fields": {"actor_id": "author", "occurred_at": "ts"},
    "event_types": {"from_field": "kind", "values": {"post": "CONTENT_CREATED/post"}},
}


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "platforms"
    directory.mkdir()
    (directory / "mini_forum.yaml").write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    (directory / "_template.yaml").write_text("not: a platform", encoding="utf-8")
    return directory


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_module, "_CUSTOM_ADAPTERS", {})


def test_available_platforms_skips_template(config_dir: Path) -> None:
    assert available_platforms(config_dir) == ["mini_forum"]
    assert available_platforms(config_dir / "missing") == []


def test_load_generic_adapter(config_dir: Path, tmp_path: Path) -> None:
    adapter = load_adapter("mini_forum", config_dir=config_dir, base_dir=tmp_path)
    assert isinstance(adapter, GenericAdapter)
    assert adapter.source_path == tmp_path / "raw" / "forum.jsonl"


def test_unknown_platform(config_dir: Path) -> None:
    with pytest.raises(PlatformConfigError, match="not found"):
        load_adapter("nowhere", config_dir=config_dir)


class FakeAdapter:
    def __init__(self, config: PlatformConfig, base_dir: Path) -> None:
        self.platform = config.platform
        self.base_dir = base_dir

    def read(self) -> Iterator[RawRecord]:
        return iter(())

    def to_events(self, record: RawRecord) -> list[Event | Rejection]:
        return []

    def new_report(self) -> MappingReport:
        return MappingReport(self.platform)


def test_custom_adapter_takes_precedence(config_dir: Path, tmp_path: Path) -> None:
    register_custom_adapter("mini_forum", FakeAdapter)
    adapter = load_adapter("mini_forum", config_dir=config_dir, base_dir=tmp_path)
    assert isinstance(adapter, FakeAdapter)
    assert adapter.base_dir == tmp_path
