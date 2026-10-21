"""The Stack Exchange converter and platform file, on a tiny hand-made dump."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from riskdetect.adapters import GenericAdapter, load_platform_config, run_adapter
from riskdetect.schema import ContentKind, Event, EventType

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def converter() -> ModuleType:
    path = PROJECT_ROOT / "scripts" / "stackexchange_to_jsonl.py"
    spec = importlib.util.spec_from_file_location("stackexchange_to_jsonl", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_dump(folder: Path) -> None:
    folder.mkdir(parents=True)
    (folder / "Users.xml").write_text(
        '<users><row Id="-1" CreationDate="2016-07-19T17:00:00.000" Reputation="1" />'
        '<row Id="7" CreationDate="2016-07-19T17:27:07.750" Reputation="1200" '
        'WebsiteUrl="https://example.com" />'
        '<row Id="8" CreationDate="2016-07-20T09:00:00.000" Reputation="1" /></users>',
        encoding="utf-8",
    )
    (folder / "PostHistory.xml").write_text(
        "<posthistory>"
        '<row Id="1" PostHistoryTypeId="1" PostId="10" UserId="7" '
        'CreationDate="2016-07-20T10:00:00.000" Text="How do subaddresses work?" />'
        '<row Id="2" PostHistoryTypeId="2" PostId="10" UserId="7" '
        'CreationDate="2016-07-20T10:00:00.000" Text="See https://getmonero.org/docs please" />'
        '<row Id="3" PostHistoryTypeId="3" PostId="10" UserId="7" '
        'CreationDate="2016-07-20T10:00:00.000" Text="|wallet|subaddress|" />'
        '<row Id="4" PostHistoryTypeId="2" PostId="11" UserId="8" '
        'CreationDate="2016-07-20T11:00:00.000" Text="An answer" />'
        '<row Id="5" PostHistoryTypeId="5" PostId="11" UserId="8" '
        'CreationDate="2016-07-21T11:00:00.000" Text="An edited answer" />'
        "</posthistory>",
        encoding="utf-8",
    )
    (folder / "Comments.xml").write_text(
        '<comments><row Id="20" PostId="10" UserId="8" CreationDate="2016-07-20T12:00:00.000" '
        'Text="Thanks!" /><row Id="21" PostId="10" CreationDate="2016-07-20T12:01:00.000" '
        'Text="from a deleted user" /></comments>',
        encoding="utf-8",
    )
    (folder / "Votes.xml").write_text(
        '<votes><row Id="1" PostId="11" VoteTypeId="12" CreationDate="2016-07-22T00:00:00.000" />'
        '<row Id="2" PostId="10" VoteTypeId="2" CreationDate="2016-07-22T00:00:00.000" /></votes>',
        encoding="utf-8",
    )


def test_converter_rebuilds_posts_from_history(tmp_path: Path) -> None:
    write_dump(tmp_path / "extracted")
    counts = converter().convert(tmp_path / "extracted", tmp_path / "out")
    assert counts == {"events": 5, "users": 2, "spam_votes": 1}

    lines = (tmp_path / "out" / "export" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert [e["action"] for e in events] == ["signup", "signup", "question", "answer", "comment"]
    question = events[2]
    assert question["space"] == "wallet"
    assert question["text"].startswith("How do subaddresses work?")
    assert events[3]["text"] == "An answer"  # the first version, not later edits
    assert events[4]["parent_owner"] == "7"  # who received the comment

    spam = json.loads((tmp_path / "out" / "meta" / "spam_votes.jsonl").read_text(encoding="utf-8"))
    assert spam["owner"] == "8"


def test_platform_file_reads_the_export_with_no_code(tmp_path: Path) -> None:
    write_dump(tmp_path / "extracted")
    converter().convert(tmp_path / "extracted", tmp_path / "data/raw/stackexchange_monero")
    config = load_platform_config(
        PROJECT_ROOT / "configs" / "platforms" / "stackexchange_monero.yaml"
    )
    adapter = GenericAdapter(config, base_dir=tmp_path)
    results = list(run_adapter(adapter, adapter.new_report()))
    assert all(isinstance(r, Event) for r in results)
    by_id = {r.event_id: r for r in results if isinstance(r, Event)}
    assert by_id["stackexchange_monero:signup-7"].event_type is EventType.ACCOUNT_CREATED
    question = by_id["stackexchange_monero:post-10"]
    assert question.content is not None
    assert question.content.kind is ContentKind.POST
    assert question.content.url_domains == ("getmonero.org",)
    comment = by_id["stackexchange_monero:comment-20"]
    assert comment.target is not None and comment.target.owner_actor_id == "7"
