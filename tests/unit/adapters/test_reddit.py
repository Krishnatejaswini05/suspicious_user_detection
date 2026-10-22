"""The Reddit converter and platform file, on tiny hand-made archive shards."""

import importlib.util
from pathlib import Path
from types import ModuleType

import duckdb

from riskdetect.adapters import GenericAdapter, load_platform_config, run_adapter
from riskdetect.schema import ContentKind, Event

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def converter() -> ModuleType:
    path = PROJECT_ROOT / "scripts" / "reddit_to_parquet.py"
    spec = importlib.util.spec_from_file_location("reddit_to_parquet", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_shards(folder: Path) -> None:
    folder.mkdir(parents=True)
    submissions = (folder / "submissions_2008_11_000.parquet").as_posix()
    comments = (folder / "comments_2008_11_000.parquet").as_posix()
    duckdb.execute(f"""
        copy (select * from (values
            ('a1', 'alice', 'pics', 'My cat', '', 1225500000, 'http://imgur.com/cat'),
            ('a2', 'bob', 'askreddit', 'A question', 'Body text', 1225500100,
             'http://www.reddit.com/r/askreddit/comments/a2/a_question/'),
            ('a3', '[deleted]', 'pics', 'Gone', '[deleted]', 1225500200, 'http://x.org/'),
            ('a4', 'carol', 'news', 'Removed one', '[removed]', 1225500300, 'http://y.org/1')
        ) t(id, author, subreddit, title, selftext, created_utc, url)) to '{submissions}'
        (format parquet)
    """)
    duckdb.execute(f"""
        copy (select * from (values
            ('c1', 'bob', 'pics', 'Nice cat', 1225500400, 't3_a1'),
            ('c2', 'alice', 'pics', 'Thanks!', 1225500500, 't1_c1'),
            ('c3', '[deleted]', 'pics', 'whatever', 1225500600, 't3_a1'),
            ('c4', 'carol', 'pics', 'Reply to a ghost', 1225500700, 't3_a3')
        ) t(id, author, subreddit, body, created_utc, parent_id)) to '{comments}'
        (format parquet)
    """)


def test_converter_merges_posts_and_comments(tmp_path: Path) -> None:
    write_shards(tmp_path / "download")
    counts = converter().convert(tmp_path / "download", tmp_path / "out")
    assert counts == {"events": 6, "users": 3}  # deleted authors are dropped

    events = {
        row[0]: row
        for row in duckdb.execute(
            "select id, user, action, text, parent_owner from read_parquet(?)",
            [(tmp_path / "out" / "export" / "events.parquet").as_posix()],
        ).fetchall()
    }
    assert events["post-a1"][3] == "My cat http://imgur.com/cat"
    assert "reddit.com" not in events["post-a2"][3]  # a text post's own URL is not a link
    assert events["comment-c1"][4] == "alice"  # who received the comment
    assert events["comment-c2"][4] == "bob"
    assert events["comment-c4"][4] is None  # replying to a deleted author

    hints = duckdb.execute(
        "select user, posts, comments, removed_posts from read_parquet(?) order by user",
        [(tmp_path / "out" / "meta" / "hints.parquet").as_posix()],
    ).fetchall()
    assert hints == [("alice", 1, 1, 0), ("bob", 1, 1, 0), ("carol", 1, 1, 1)]


def test_platform_file_reads_the_export_with_no_code(tmp_path: Path) -> None:
    write_shards(tmp_path / "download")
    converter().convert(tmp_path / "download", tmp_path / "data/raw/reddit")
    config = load_platform_config(PROJECT_ROOT / "configs" / "platforms" / "reddit.yaml")
    adapter = GenericAdapter(config, base_dir=tmp_path)
    results = list(run_adapter(adapter, adapter.new_report()))
    assert all(isinstance(r, Event) for r in results)
    by_id = {r.event_id: r for r in results if isinstance(r, Event)}
    post = by_id["reddit:post-a1"]
    assert post.content is not None and post.content.kind is ContentKind.POST
    assert post.content.url_domains == ("imgur.com",)
    assert post.space_id == "pics"
    comment = by_id["reddit:comment-c1"]
    assert comment.content is not None and comment.content.kind is ContentKind.REPLY
    assert comment.target is not None and comment.target.owner_actor_id == "alice"
