# riskdetect — Design

Status: agreed design, implementation in progress (Milestones 1-10 complete).
Key decisions are recorded as ADRs in [adr/](adr/).

## 1. Problem

For an account (an *actor*) on any platform, use its behavior up to time *t* to produce:

- a **risk score** in [0, 1] estimating how likely the actor is engaged in a defined
  kind of abuse, with a sub-score per category;
- a **confidence** level reflecting how much evidence we have;
- a **tier** (LOW / WATCH / REVIEW / HIGH) and recommended actions;
- **reasons** a person can read.

Abuse categories: spam/promotion, automation/bots, account takeover (hijacked),
scams, coordinated inauthentic behavior. v1 focuses on **spam and bots**.

Non-goals: judging content harm, identity verification, enforcing actions.
The system recommends; the platform decides.

Constraints:

- **New accounts are not suspicious by default.** Age is one feature, never the sole
  reason for a flag. Little data → low confidence, not high risk.
- **Detect fast**: minutes after abuse starts, not at the next weekly batch.
- **Point-in-time correctness**: anything computed for time *t* uses only data before *t*.
- **Explainable**, **fair** (false-positive rate monitored per segment), and
  **works on a new platform from day one** (no labels needed to start).

## 2. Platform independence

Achieved at four layers:

1. **Data** — every platform's data is mapped into one canonical `Event` format by a
   generic adapter driven by a per-platform YAML file. Adding a platform means adding
   a YAML file, not code ([ADR 004](adr/004-config-driven-adapters.md)).
2. **Features** — each feature declares the fields it needs and is enabled only where
   those fields exist. Missing is recorded as *missing*, never as zero.
3. **Model inputs** — features are *relative*: percentile within the actor's platform,
   or ratio to the actor's own baseline. "Top 0.1% here" means the same everywhere.
4. **Learning** — rules and anomaly detection need no labels; a shared classifier is
   calibrated per platform and improves as reviewer decisions arrive.

Proof: a platform-holdout evaluation (train on some platforms, test on an unseen one).

## 3. Canonical data model (`riskdetect.schema`)

See [ADR 001](adr/001-canonical-event-model.md).

`Event` — one thing one actor did at one time:

| Field | Notes |
|---|---|
| `event_id` | Stable; drives dedupe. Platform ID when available, else derived (see `schema/ids.py`) |
| `schema_version` | Currently 1 |
| `platform` | Lowercase identifier |
| `actor_id` | Who acted (for `MODERATION_ACTION`: the subject account) |
| `event_type` | `ACCOUNT_CREATED`, `CONTENT_CREATED`, `CONTENT_EDITED`, `CONTENT_DELETED`, `INTERACTION`, `REPORT_FILED`, `MODERATION_ACTION`, `PROFILE_UPDATED` |
| `occurred_at` / `ingested_at` | Timezone-aware, stored in UTC |
| `space_id` | Where (community, channel, category) |
| `target` | What it was aimed at: `{type, id, owner_actor_id}` |
| `content` | `{kind, visibility, text_hash, simhash, length, language, url_domains, mention_count}` — no raw text |
| `interaction` | `{kind, value}` |
| `moderation` | `{action, source, reason_category}` |
| `attributes` | Flat platform-specific extras; never read by core logic |

Each event type requires and allows specific blocks (e.g. `INTERACTION` needs
`interaction` and `target`). Violations are rejected at construction.

Other entities: `Actor`, `Space`, `Label`. Labels are a separate type and store so the
detector cannot read them.

Untrusted input goes through `parse_event`, which returns an `Event` or a `Rejection`
with a reason; rejections are quarantined, not dropped.

## 4. Architecture

```
platform data + platform YAML
        │
        ▼
adapters/  ──▶ ingestion/ (validate, dedupe, store, publish)
                  │                     │
                  ▼                     ▼
              storage/            realtime/ (per-actor running state)
          (Parquet + DuckDB)        │  inline rules → rescore when triggered
                  │                 ▼
                  │             scoring/ ◀── rules/ · models/ · explain/
                  │                 │
                  ▼                 ▼
          features/ (batch)    score store ──▶ serving/ (API, review queue)
                  │                                   │
                  ▼                                   ▼
        training (models/) ◀── labels/ ◀──── reviewer decisions
                  │
                  ▼
            evaluation/ (gates before release)
```

### Scoring is event-driven ([ADR 003](adr/003-event-driven-scoring.md))

- **Tier 0 — inline rules** on each event (milliseconds): bursts, duplicates, blocked domains.
- **Tier 1 — incremental rescore** of the acting user (seconds–minutes), debounced.
- **Tier 2 — periodic batch** (daily/weekly): expensive features, coordination,
  percentile refresh, score decay. A backstop, not the primary detector.

Inactive users cost nothing; risk only changes when a user acts.

### Storage ([ADR 005](adr/005-duckdb-and-parquet.md))

Parquet files hold data; DuckDB queries them. Only `storage/` knows this. Stores:
events (append-only, partitioned by platform/date, with "up to time *t*" reads),
features (offline snapshots + online latest), scores (with history), labels,
quarantine. A controlled `delete_actor` supports privacy requests.

## 5. Features

Computed per actor over windows 1h / 24h / 7d / 30d / lifetime. Each actor has one running
summary (`features/state.py`) updated event by event; each feature is a formula over that
summary as of a moment. Batch replays stored events through it; realtime will feed live
events through the same code, which keeps the two in agreement.

| Family | v1 examples |
|---|---|
| Lifecycle | account age, time to first post, dormancy gap |
| Volume | posts per window, interactions per window |
| Temporal | timing regularity, burstiness, hour-of-day spread |
| Change | rate vs own baseline, reactivation after dormancy |
| Content | duplicate ratio, link ratio, distinct domains, shortener ratio |
| Evidence | events seen, feature coverage (→ confidence, not risk) |

Later: interaction/graph features, cross-actor similarity, coordination.

Raw counts are converted to per-platform percentiles. Already-relative features
(ratios) are used as-is.

Links are a strong spam/scam signal but are judged by *pattern* (always the same
domain, shorteners, blocked domains), never by presence alone, and are never visited.

## 6. Detection layers

| Layer | Needs labels | Role |
|---|---|---|
| Rules (`rules/`) | No | Obvious cases; fairness guardrails; config-driven, versioned, shadow mode |
| Population anomaly (Isolation Forest) | No | Unusual vs peers on this platform |
| Self-baseline anomaly | No | Unusual vs the actor's own history (account takeover) |
| Classifier (LightGBM, per category) | Yes | Subtle combinations; calibrated per platform |

**Rule vs ML split.** Rules: known-bad indicators, hard limits, allow/blocklists,
guardrails, mapping scores to actions. ML: weighing weak signals, interactions,
novel patterns, ranking.

**Guardrails** (cannot be bypassed): age is never the sole reason; low evidence cannot
reach HIGH unless a strong rule fired; HIGH needs two independent pieces of evidence unless
a critical rule fired; allowlisted accounts are capped; every flag above WATCH has a reason.
Model trust rules are in [ADR 006](adr/006-plain-python-models-and-trust.md).

## 7. Scoring

1. features → 2. scoring rules → 3. anomaly → 4. classifier → 5. combine →
6. confidence → 7. guardrails → 8. tier and actions → 9. reasons → 10. save.

v1 combination (rules only): each fired rule removes a share of the remaining doubt,
`score = 1 - prod(1 - strength)`. Weak-signal rules alone are capped below REVIEW, so
escalating to a person needs at least one strong rule. Anomaly and model scores (later)
join the same combination. Tier depends on score **and** confidence; HIGH requires high
confidence. Scores decay when bad behavior stops.

## 8. Training and evaluation

- Snapshots at times *t*; features as of *t*; label = bad outcome within (*t*, *t*+H].
- Split by **time**, plus a **platform holdout**. Never random.
- Unreviewed actors are *unknown* (low weight), not clean.
- Leakage tests: adding future events must not change past features.
- Metrics: precision, recall, PR-AUC, precision@k (review capacity), calibration,
  **time-to-detect**, **harm before detection**, per-segment false-positive rates
  (new accounts above all), comparison to baselines (random, age-only, volume-only,
  rules-only, previous version).
- **Release gates** block any model that is worse or less fair.
- A small random sample of unflagged users is reviewed to counter feedback-loop bias.

## 9. Data sources

1. **Synthetic simulator** — three platform profiles (forum, chat, marketplace) and
   personas including hard negatives (enthusiastic new user, power user, lurker) and
   positives (spam bot, slow spammer, hijacked account; later coordinated rings).
   Produces raw platform-style data plus a hidden answer key with `abuse_start`.
2. **Reddit** public archive data (check availability and license first).
3. **A structurally different platform** (e.g. Stack Exchange data dump) to prove
   independence.

Synthetic data is for building and testing; final models must be validated and trained
on real data.

**First real run (Milestone 11).** monero.stackexchange.com connected with a YAML file
and a small converter (`scripts/stackexchange_to_jsonl.py`), with no detector changes.
Lessons: experts post many links, so "change" rules compare a user with their own past
(`link_ratio_change_24h`, `duplicate_ratio_change_24h`), not with the whole site. The dump
removes deleted posts, so spam votes cannot be linked to users and there are no real
positive labels. The thresholds were adjusted while looking at this data, so another site
is needed for an honest check.

The simulator now has those two hard negatives: `expert_linker` (always cites sources,
has answering sprees) and `maintainer` (has days of "this page moved, see <docs>" replies).
The maintainer showed that "more links than usual" is not enough to suggest a stolen
account, so the R004 rule and the self-baseline model count extra links only when they
push one site the user never linked before (`new_site_push_share_24h`).

**Second real platform: Reddit (2008).** Connected with a YAML file and a small merge
script, again with no detector changes. Lessons: self-promoters post a different article
of their own site each time, so "copied posts" rules miss them; what gives them away is
never joining in (`reply_share_7d`, rule R009). Keen sharers post a different new site
each time, so "new sites" must mean one new site pushed repeatedly. No real labels exist
in the archive; checks are by reading flagged users' posts.

## 10. Milestones

| # | Milestone | Status |
|---|---|---|
| 1 | Project setup, design docs, `schema/` | **Done** |
| 2 | `synthetic/` simulator, config-driven `adapters/` | **Done** |
| 3 | `storage/`, `ingestion/` | **Done** |
| 4 | `features/` (batch) + leakage tests | **Done** |
| 5 | `rules/`, basic `scoring/`, `explain/` | **Done** |
| 6 | `realtime/` + realtime-equals-batch test | **Done** |
| 7 | `labels/`, `evaluation/` | **Done** |
| 8 | Anomaly models | **Done** |
| 9 | Classifier, calibration, combiner | **Done** |
| 10 | `serving/` (API + CLI) | **Done** |
| 11 | First real-data adapter (Stack Exchange) | **Done** |
| 12 | Second real platform (Reddit: done); coordination across accounts (done: site pushes, copy campaigns, raids, invite floods); monitoring | In progress |
