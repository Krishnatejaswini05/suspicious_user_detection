"""Run the detector's HTTP API.

    python -m riskdetect.serving                       # http://127.0.0.1:8000
    python -m riskdetect.serving --port 9000

Set the RISKDETECT_API_KEY environment variable to require an X-API-Key header.
By default it listens on this computer only; use --host 0.0.0.0 to accept other
machines (and then always set an API key).
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
    args = parser.parse_args(argv)

    api_key = os.environ.get("RISKDETECT_API_KEY") or None
    if args.host not in ("127.0.0.1", "localhost") and api_key is None:
        print("Refusing to listen beyond this computer without RISKDETECT_API_KEY set.")
        return 2

    print("Loading platforms, models and history (warming up the live desk)...")
    service = DetectorService(ServiceConfig(data_root=args.data, config_dir=args.config_dir))
    server = ApiServer((args.host, args.port), service, api_key=api_key)
    host, port = server.server_address[:2]
    print(f"Listening on http://{host!s}:{port}  (API key {'required' if api_key else 'off'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping.", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
