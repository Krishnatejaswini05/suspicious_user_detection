"""Run the scenario library and write a report.

    python -m riskdetect.scenarios                  # all scenarios -> data/reports/scenarios.md
    python -m riskdetect.scenarios --only spam_ring --only traveller

Exits with status 1 if any scenario fails that is not a known gap.
"""

import argparse
import sys
import time
from pathlib import Path

from riskdetect.scenarios import SCENARIOS, run_all, to_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m riskdetect.scenarios", description=__doc__)
    parser.add_argument("--only", action="append", help="scenario name (repeatable)")
    parser.add_argument("--out", type=Path, default=Path("data/reports/scenarios.md"))
    args = parser.parse_args(argv)

    chosen = SCENARIOS
    if args.only:
        known = {s.name for s in SCENARIOS}
        unknown = set(args.only) - known
        if unknown:
            print(f"Unknown scenarios: {sorted(unknown)}", file=sys.stderr)
            return 2
        chosen = [s for s in SCENARIOS if s.name in args.only]

    started = time.monotonic()
    results = run_all(chosen)
    report = to_markdown(results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    print(f"{len(results)} scenarios in {time.monotonic() - started:.0f}s -> {args.out}")
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
