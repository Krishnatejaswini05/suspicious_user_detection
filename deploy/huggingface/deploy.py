"""Publish one tested commit to the Hugging Face Space (run by CI on main).

    HF_TOKEN=... HF_SPACE=<user>/<space> GITHUB_SHA=<commit> python deploy/huggingface/deploy.py

Uploads the Space's README and a Dockerfile pinned to that commit; the Space then
rebuilds itself from exactly the code that passed the tests.
"""

import os
import re
import sys
from pathlib import Path

from huggingface_hub import HfApi

HERE = Path(__file__).resolve().parent


def main() -> int:
    token = os.environ.get("HF_TOKEN")
    space = os.environ.get("HF_SPACE")
    commit = os.environ.get("GITHUB_SHA")
    if not token or not space or not commit:
        print("HF_TOKEN, HF_SPACE and GITHUB_SHA must all be set.", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        print(f"GITHUB_SHA is not a commit id: {commit!r}", file=sys.stderr)
        return 2

    dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
    pinned, count = re.subn(r"^ARG REF=.*$", f"ARG REF={commit}", dockerfile, flags=re.M)
    if count != 1:
        print("Dockerfile has no single 'ARG REF=' line to pin.", file=sys.stderr)
        return 2

    api = HfApi(token=token)
    message = f"Deploy {commit[:7]} from GitHub"
    api.upload_file(
        path_or_fileobj=(HERE / "README.md").read_bytes(),
        path_in_repo="README.md",
        repo_id=space,
        repo_type="space",
        commit_message=message,
    )
    api.upload_file(
        path_or_fileobj=pinned.encode("utf-8"),
        path_in_repo="Dockerfile",
        repo_id=space,
        repo_type="space",
        commit_message=message,
    )
    print(f"Deployed {commit[:7]} to https://huggingface.co/spaces/{space}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
