"""Convert a Stack Exchange data dump (one site, extracted) into a JSON-lines export.

    python -I scripts/stackexchange_to_jsonl.py <extracted-dir> <output-dir>

Writes, under <output-dir>:
- export/events.jsonl  - one row per signup, question, answer and comment, in time order;
                         read by the generic adapter via configs/platforms/<site>.yaml
- meta/users.jsonl     - reputation and profile facts, for checking results only
- meta/spam_votes.jsonl - posts the community voted as spam, for checking results only

The dump is CC BY-SA (see its license.txt): keep attribution with any derived data.

Recent dumps may omit Posts.xml; posts are then rebuilt from PostHistory.xml, where
every post's first version ("Initial Body", plus "Initial Title"/"Initial Tags" for
questions) is recorded with its author and time. Deleted posts are scrubbed from the
dump, so most removed spam is not present. Votes carry no voter, so they cannot be
attributed to users and are not exported as events.

Uses only the standard library and reads the files as untrusted data.
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

INITIAL_TITLE, INITIAL_BODY, INITIAL_TAGS = "1", "2", "3"
SPAM_VOTE = "12"
_TAG = re.compile(r"[<|]([^<>|]+)[>|]")


def rows(path: Path) -> Iterator[dict[str, str]]:
    """Stream <row .../> elements as attribute dicts, without loading the whole file."""
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag == "row":
            yield dict(element.attrib)
            element.clear()


def first_tag(tags: str | None) -> str | None:
    if not tags:
        return None
    found = _TAG.findall(tags)
    return found[0] if found else None


def convert(extracted: Path, out: Path) -> dict[str, int]:
    posts: dict[str, dict[str, Any]] = {}
    for row in rows(extracted / "PostHistory.xml"):
        post = posts.setdefault(row["PostId"], {})
        kind = row["PostHistoryTypeId"]
        if kind == INITIAL_BODY:
            post.update(user=row.get("UserId"), time=row["CreationDate"], body=row.get("Text", ""))
        elif kind == INITIAL_TITLE:
            post["title"] = row.get("Text", "")
        elif kind == INITIAL_TAGS:
            post["tags"] = row.get("Text", "")

    events: list[dict[str, Any]] = []
    users: list[dict[str, Any]] = []
    for row in rows(extracted / "Users.xml"):
        if row["Id"] == "-1":
            continue  # the "Community" system account
        users.append(
            {
                "user": row["Id"],
                "created": row["CreationDate"],
                "reputation": int(row.get("Reputation", "0")),
                "has_website": bool(row.get("WebsiteUrl")),
            }
        )
        events.append(
            {
                "id": f"signup-{row['Id']}",
                "user": row["Id"],
                "action": "signup",
                "time": row["CreationDate"],
            }
        )

    for post_id, post in posts.items():
        if "time" not in post or not post.get("user"):
            continue  # no initial body (e.g. scrubbed), or the author's account was deleted
        is_question = "title" in post
        text = f"{post['title']}\n\n{post['body']}" if is_question else post["body"]
        events.append(
            {
                "id": f"post-{post_id}",
                "user": post["user"],
                "action": "question" if is_question else "answer",
                "time": post["time"],
                "space": first_tag(post.get("tags")),
                "text": text,
            }
        )

    for row in rows(extracted / "Comments.xml"):
        if not row.get("UserId"):
            continue
        parent = posts.get(row["PostId"], {})
        events.append(
            {
                "id": f"comment-{row['Id']}",
                "user": row["UserId"],
                "action": "comment",
                "time": row["CreationDate"],
                "text": row.get("Text", ""),
                "parent_id": f"post-{row['PostId']}",
                "parent_owner": parent.get("user"),
            }
        )

    spam = [
        {
            "post": f"post-{row['PostId']}",
            "owner": posts.get(row["PostId"], {}).get("user"),
            "time": row["CreationDate"],
        }
        for row in rows(extracted / "Votes.xml")
        if row["VoteTypeId"] == SPAM_VOTE
    ]

    events.sort(key=lambda e: (e["time"], e["id"]))
    (out / "export").mkdir(parents=True, exist_ok=True)
    (out / "meta").mkdir(parents=True, exist_ok=True)
    _write(out / "export" / "events.jsonl", events)
    _write(out / "meta" / "users.jsonl", users)
    _write(out / "meta" / "spam_votes.jsonl", spam)
    return {"events": len(events), "users": len(users), "spam_votes": len(spam)}


def _write(path: Path, items: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    counts = convert(Path(sys.argv[1]), Path(sys.argv[2]))
    print(", ".join(f"{name}: {count:,}" for name, count in counts.items()))
