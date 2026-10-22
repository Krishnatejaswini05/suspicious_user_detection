#!/bin/sh
# Build the public demo's data: simulated users on three platforms, run through the
# whole pipeline. Run from the project root. Only synthetic data: no real people.
set -eu

PLATFORMS="--platform synthetic_forum --platform synthetic_chat --platform synthetic_market"

python -m riskdetect.synthetic --scenario configs/scenarios/basic_v1.yaml --out data
python -m riskdetect.ingestion $PLATFORMS
python -m riskdetect.features $PLATFORMS
python -m riskdetect.models
python -m riskdetect.scoring $PLATFORMS --all-snapshots --top 0
