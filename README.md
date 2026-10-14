# riskdetect

Platform-agnostic user behavior risk detection.

`riskdetect` analyzes how accounts behave over time and produces a **risk score**
with a **confidence level** and **readable reasons**. It is designed to work on any
platform (forums, chat, marketplaces) by translating each platform's data into one
common event format, configured with a YAML file rather than code.

Core principles:

- **New accounts are not suspicious by default.** Account age is one feature among
  many and is never the only reason for a flag. Little data means low *confidence*,
  not high *risk*.
- **Detect fast.** Scoring is triggered by user activity, not a weekly batch.
- **Explain every flag.** Each score comes with the reasons behind it.
- **Recommend, don't enforce.** The platform decides what action to take.
- **Privacy by default.** Raw text is reduced to fingerprints and never stored.

See [docs/design.md](docs/design.md) for the full design and
[docs/adr/](docs/adr/) for the key decisions.

## Status

- Milestone 1: project setup and the canonical schema (`riskdetect.schema`). Done.
- Milestone 2a: config-driven adapters (`riskdetect.adapters`). Done.
- Milestone 2b: synthetic data simulator (`riskdetect.synthetic`). Done.
- Milestone 3: storage and ingestion (`riskdetect.storage`, `riskdetect.ingestion`). Done.
- Milestone 4: behavioral features (`riskdetect.features`). Done.
- Milestone 5: rules, basic scoring and explanations. Next.

To connect a platform, copy [configs/platforms/_template.yaml](configs/platforms/_template.yaml).

## Generate synthetic data

```bash
python -m riskdetect.synthetic                  # uses configs/scenarios/basic_v1.yaml, writes to data/
```

This writes raw files for three simulated platforms (forum, chat, marketplace) under
`data/raw/` and the hidden answer key to `data/labels/answer_key.parquet`. The same
seed always produces the same data.

## Load data into the event store

```bash
python -m riskdetect.ingestion                  # every platform in configs/platforms/
python -m riskdetect.ingestion --platform synthetic_forum
```

Raw files are translated by the adapters, deduplicated, and stored as Parquet under
`data/events/platform=<p>/date=<YYYY-MM-DD>/`. Rejected rows go to `data/quarantine/`.
Loading the same files again stores nothing new.

## Compute behavioral features

```bash
python -m riskdetect.features                   # daily snapshots for every platform
```

Each snapshot holds every active user's features as of that moment, computed only
from earlier events. Count features also get a `<name>_pct` column: their percentile
within the platform. Output: `data/features/platform=<p>/snapshots.parquet`.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

## Development

```bash
pytest          # run tests
ruff check .    # lint
ruff format .   # format
mypy src        # type check
```

## Layout

```
configs/            settings: shared logic + one YAML file per platform
docs/               design and decision records
src/riskdetect/
  schema/           the common, platform-neutral data format
  adapters/         raw platform data -> Events, using the platform YAML
  synthetic/        simulated users and platforms with a known answer key
  ingestion/        the front door: dedupe, store, publish; quarantine rejections
  storage/          where data lives (Parquet via DuckDB, no PyArrow); the only package that knows
  features/         behavior -> numbers, as of a moment in time, never seeing the future
tests/              unit, integration and invariant tests
data/               local data (not in git)
```

Further packages (`realtime`, `rules`, `models`, `scoring`, `explain`, `labels`,
`evaluation`, `serving`) are added milestone by milestone; see the design doc.
