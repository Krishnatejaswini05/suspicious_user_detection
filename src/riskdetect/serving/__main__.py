"""Run the detector's HTTP API.

    python -m riskdetect.serving                       # http://127.0.0.1:8000
    python -m riskdetect.serving --port 9000
    python -m riskdetect.serving --platform reddit     # only some platforms (faster start)

Open the address in a browser for the reviewer dashboard.

Set the RISKDETECT_API_KEY environment variable to require an X-API-Key header.
By default it listens on this computer only; use --host 0.0.0.0 to accept other
machines (and then always set an API key).

    python -m riskdetect.serving --demo --host 0.0.0.0 --port 7860

--demo is for a public showcase on synthetic data: it may listen beyond this
computer without a key, and switches off sending events (POST /events).
"""

import argparse
import os
import sys
from pathlib import Path

from riskdetect.adapters import DEFAULT_CONFIG_DIR
from riskdetect.serving.http import ApiServer
from riskdetect.serving.service import DetectorService, ServiceConfig
from riskdetect.storage import DEFAULT_DATA_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m riskdetect.serving", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--platform", action="append", help="platform to serve (repeatable)")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="public showcase on synthetic data: no key needed, sending events switched off",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("RISKDETECT_API_KEY") or None
    if args.host not in ("127.0.0.1", "localhost") and api_key is None and not args.demo:
        print("Refusing to listen beyond this computer without RISKDETECT_API_KEY set.")
        print("(For a public showcase on synthetic data, use --demo.)")
        return 2
    if args.demo:
        print("Demo mode: sending events is off; decisions are kept only until restart.")

    print("Loading platforms, models and history (warming up the live desk)...")
    platforms = tuple(args.platform) if args.platform else None
    service = DetectorService(
        ServiceConfig(data_root=args.data, config_dir=args.config_dir, platforms=platforms)
    )
    server = ApiServer((args.host, args.port), service, api_key=api_key, demo=args.demo)
    host, port = server.server_address[:2]
    print(f"Listening on http://{host!s}:{port}  (API key {'required' if api_key else 'off'})")
    print(f"Reviewer dashboard: http://{host!s}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping.", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
