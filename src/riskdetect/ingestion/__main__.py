"""Ingest platforms from the command line.

python -m riskdetect.ingestion                         # every configured platform
python -m riskdetect.ingestion --platform synthetic_forum
"""

import argparse
from pathlib import Path

from riskdetect.adapters import DEFAULT_CONFIG_DIR, available_platforms
from riskdetect.ingestion.load import default_pipeline, ingest_platform
from riskdetect.storage import DEFAULT_DATA_ROOT, DataPaths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m riskdetect.ingestion",
        description="Translate raw platform files and store the resulting events.",
    )
    parser.add_argument("--platform", action="append", help="platform to ingest (repeatable)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_ROOT, help="data folder")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        help="folder that platform source paths (e.g. data/raw/...) are relative to; "
        "default: the current folder",
    )
    args = parser.parse_args(argv)

    platforms = args.platform or available_platforms(args.config_dir)
    pipeline = default_pipeline(DataPaths(args.data))
    for platform in platforms:
        mapping, ingest = ingest_platform(
            platform, pipeline=pipeline, config_dir=args.config_dir, base_dir=args.base_dir
        )
        print(mapping.summary())
        print(ingest.summary())
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
