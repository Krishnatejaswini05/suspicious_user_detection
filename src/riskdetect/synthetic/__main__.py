"""Generate synthetic data from the command line.

python -m riskdetect.synthetic
python -m riskdetect.synthetic --scenario configs/scenarios/basic_v1.yaml --out data
"""

import argparse
from pathlib import Path

from riskdetect.synthetic.generator import simulate
from riskdetect.synthetic.scenario import load_scenario
from riskdetect.synthetic.writer import write_simulation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m riskdetect.synthetic",
        description="Generate simulated platform data and its answer key.",
    )
    parser.add_argument("--scenario", type=Path, default=Path("configs/scenarios/basic_v1.yaml"))
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args(argv)

    result = simulate(load_scenario(args.scenario))
    written = write_simulation(result, args.out)
    print(result.summary())
    for name, path in written.items():
        print(f"  wrote {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
