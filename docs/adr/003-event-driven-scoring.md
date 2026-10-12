# ADR 003: Event-driven scoring, with batch as a backstop

Status: accepted

## Context

Scoring on a fixed schedule (for example weekly) means an account that starts abusing
on day 2 is caught on day 7, after the harm is done.

## Decision

Scoring is triggered by activity:

- **Inline rules** run on every event and can recommend immediate friction.
- The acting user's **running state** is updated incrementally and the user is
  **rescored** when debounce triggers fire (a rule fired, N new events, M minutes,
  a large feature jump, or a late event).
- A **periodic batch** handles expensive features, percentile refresh and score decay.

Feature windows (1h…30d) describe what a feature looks at, not how often it runs.
Each feature is defined once and shared by the realtime and batch paths.

## Consequences

- Time-to-detect is minutes for bursty abuse; it becomes a tracked metric.
- Inactive users cost nothing.
- Realtime and batch must agree; enforced by a replay test.
- v1 runs in-process; a message queue can replace the publisher later without
  changing other packages.
