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

Milestone 1: project setup and the canonical schema (`riskdetect.schema`).

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
tests/              unit, integration and invariant tests
data/               local data (not in git)
```

Further packages (`adapters`, `synthetic`, `ingestion`, `storage`, `features`,
`realtime`, `rules`, `models`, `scoring`, `explain`, `labels`, `evaluation`,
`serving`) are added milestone by milestone; see the design doc.
