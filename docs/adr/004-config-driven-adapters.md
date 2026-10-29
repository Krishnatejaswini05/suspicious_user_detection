# ADR 004: One generic adapter, configured per platform with YAML

Status: accepted

## Context

Writing a Python adapter per platform makes onboarding a development task and lets
platform logic creep into code.

## Decision

- One generic adapter reads raw data (CSV, JSON lines, Parquet) and maps it to `Event`s
  using `configs/platforms/<platform>.yaml`: field mapping, action → event type mapping,
  and rare, whitelisted overrides.
- Platform files describe **data**, never detection **logic**. Logic lives in shared
  config (`features.yaml`, the rule packs in `rules/`, `scoring.yaml`).
- Configs are validated on load; a `validate-platform` command reports mapping results
  and which features are enabled.
- Custom code adapters are allowed only for sources YAML cannot describe, and must
  still emit canonical `Event`s.
- Later: schema inference suggests a mapping from sample data for a human to confirm.

## Consequences

- A new platform needs one YAML file and no code changes; this is an invariant test.
- The YAML mapping language must stay small to remain understandable.
