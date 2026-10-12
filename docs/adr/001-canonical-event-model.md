# ADR 001: A canonical, platform-neutral event model

Status: accepted

## Context

The system must detect risky behavior on any platform: forums, chat, marketplaces.
Each platform names and structures its activity differently (posts, messages, listings,
upvotes, reactions). If features, rules or models read platform-specific data, the
system becomes tied to each platform.

## Decision

All data is translated into one `Event` format (`riskdetect.schema`) before anything
else touches it:

- A small, closed set of event types and content/interaction kinds. Platforms map onto
  these; the lists do not grow per platform.
- Platform-specific extras go into a flat `attributes` map that core logic never reads.
- Each event type requires and allows specific blocks, enforced at construction.
- Timestamps must be timezone-aware and are stored in UTC.
- Models are immutable and reject unknown fields, so mapping mistakes fail loudly.
- Untrusted input yields an `Event` or a `Rejection` with a reason, never a silent drop.

## Consequences

- Everything downstream of adapters is platform-agnostic by construction.
- Some platform nuance is lost unless an adapter maps it to a canonical field.
- Changing the format requires a schema version bump.
