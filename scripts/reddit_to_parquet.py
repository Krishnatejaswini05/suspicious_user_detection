"""Merge Reddit archive shards (Arctic Shift Parquet) into one export the adapter can read.

    python -I scripts/reddit_to_parquet.py <download-dir> <output-dir>

<download-dir> holds the monthly shards, saved as comments_*.parquet and
submissions_*.parquet. Writes, under <output-dir>:
- export/events.parquet - one row per post (submission) and comment, in time order;
                          read by the generic adapter via configs/platforms/reddit.yaml
- meta/hints.parquet    - per-author hints for checking results only (never shown to
                          the detector): removed posts, and how much of their posting
                          goes to a single website

Rows whose author is "[deleted]" are dropped: nobody can be judged for them. They
still count as reply targets, with an unknown owner. A text post's URL points at
itself, so it is not kept as a link. Reddit content is subject to Reddit's terms;
keep the data local.

Uses DuckDB only and reads the files as untrusted data.
"""

import sys
from pathlib import Path

import duckdb

_DELETED = "'[deleted]'"
_SITE = r"regexp_extract(url, '^https?://(?:www\.)?([^/]+)', 1)"


def _quote(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def convert(download: Path, out: Path) -> dict[str, int]:
    comments = f"read_parquet({_quote(download / 'comments_*.parquet')})"
    submissions = f"read_parquet({_quote(download / 'submissions_*.parquet')})"
    (out / "export").mkdir(parents=True, exist_ok=True)
    (out / "meta").mkdir(parents=True, exist_ok=True)
    events_path = out / "export" / "events.parquet"
    hints_path = out / "meta" / "hints.parquet"

    db = duckdb.connect()
    db.execute(f"""
        create temp table owners as
        select 't3_' || id as fullname, nullif(author, {_DELETED}) as owner from {submissions}
        union all
        select 't1_' || id, nullif(author, {_DELETED}) from {comments}
    """)
    db.execute(f"""
        copy (
            select * from (
                select 'post-' || id as id, author as user, 'post' as action,
                       created_utc as time, subreddit as space,
                       concat_ws(' ', title, nullif(selftext, ''),
                                 case when url like '%/comments/' || id || '%' then null
                                      else url end) as text,
                       null::varchar as parent_id, null::varchar as parent_owner
                from {submissions} where author <> {_DELETED}
                union all
                select 'comment-' || c.id, c.author, 'comment', c.created_utc, c.subreddit,
                       c.body, c.parent_id, o.owner
                from {comments} c left join owners o on o.fullname = c.parent_id
                where c.author <> {_DELETED}
            ) order by time, id
        ) to {_quote(events_path)} (format parquet)
    """)
    db.execute(f"""
        copy (
            with posts as (
                select author, {_SITE} as site, selftext = '[removed]' as removed
                from {submissions} where author <> {_DELETED}
            ), per_site as (
                select author, site, count(*) as n from posts
                where site <> '' and site not like '%reddit.com' group by all
            ), top_site as (
                select author, arg_max(site, n) as top_site, max(n) as top_site_posts
                from per_site group by author
            ), counts as (
                select author, count(*) as posts, sum(removed::int) as removed_posts
                from posts group by author
            ), replies as (
                select author, count(*) as comments from {comments}
                where author <> {_DELETED} group by author
            )
            select coalesce(counts.author, replies.author) as user,
                   coalesce(posts, 0) as posts, coalesce(comments, 0) as comments,
                   coalesce(removed_posts, 0) as removed_posts,
                   top_site, coalesce(top_site_posts, 0) as top_site_posts
            from counts
            full join replies on replies.author = counts.author
            left join top_site on top_site.author = coalesce(counts.author, replies.author)
            order by user
        ) to {_quote(hints_path)} (format parquet)
    """)
    counts = {
        "events": db.execute(f"select count(*) from {_quote(events_path)}").fetchone(),
        "users": db.execute(f"select count(*) from {_quote(hints_path)}").fetchone(),
    }
    return {name: int(row[0]) if row else 0 for name, row in counts.items()}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    result = convert(Path(sys.argv[1]), Path(sys.argv[2]))
    print(", ".join(f"{name}: {count:,}" for name, count in result.items()))
