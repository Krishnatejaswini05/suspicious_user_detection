# Code tour

A guided reading of the code, in the order a single post travels through the system.
About 10,000 lines in `src/riskdetect/`; plan on six short sessions. Each session lists
the files to read, what to look for, something to try, and questions to check yourself.

## The big picture

```
 platform data          one shape for         numbers about         judgement            people
 (CSV, JSON, Parquet)   every platform        each user             and reasons
       │                      │                    │                    │
       ▼                      ▼                    ▼                    ▼
  adapters/  ──────►  schema/ (Event)  ──►  features/  ──────►  rules/ + models/  ──►  scoring/ + explain/
                          │                    ▲                                          │
                          ▼                    │                                          ▼
                      ingestion/  ──►  storage/ (Parquet)      realtime/ (live)      serving/ (API + dashboard)
                                                                                          │
                                                       labels/ ◄── reviewers' decisions ◄─┘
                                                          │
                                                          ▼
                                                    evaluation/ (report card)
```

Two helpers sit beside the pipeline: `synthetic/` makes fake platforms with a known
answer key, and `scenarios/` acts out situations the detector must handle.

**One idea to keep in mind everywhere:** the detector never knows which platform it is
on. Platform differences live only in `configs/platforms/*.yaml`.

---

## Session 1: What is an event? (`schema/`, about 600 lines)

Everything starts with one shape for "something a user did".

| Read | What to look for |
|---|---|
| `schema/enums.py` | The vocabulary: event types (posted, reacted, reported...), content kinds, label categories |
| `schema/events.py` | The `Event` class. Note `text_hash`, `simhash`, `url_domains`: the text itself is never stored, only fingerprints |
| `schema/validation.py` | What makes an event rejected (missing actor, time in the future...) |
| `schema/ids.py` | How every event gets a unique id, even when the platform gave none |

Also read `docs/adr/001-canonical-event-model.md` and `002-fingerprints-not-raw-text.md`.

**Try:** `pytest tests/unit/schema -q`

**Check yourself:** Why are events frozen (cannot be changed)? Why store a fingerprint
instead of the text? What happens to a post dated next year?

---

## Session 2: Getting data in (`adapters/`, `ingestion/`, `storage/`, about 2,200 lines)

How a row in some platform's file becomes a stored `Event`.

| Read | What to look for |
|---|---|
| `configs/platforms/_template.yaml`, then `reddit.yaml` | A platform described in YAML only: column names, action mapping, `own_domains` |
| `adapters/config_loader.py` | How the YAML is checked (unknown keys are errors, not ignored) |
| `adapters/generic.py` | The one adapter for every platform: row → Event, or row → Rejection with a reason |
| `adapters/transforms.py` | Time parsing, text fingerprints, link domains, dropping the platform's own domains |
| `ingestion/pipeline.py` | The front door: dedupe → store → publish to live scoring; rejections go to quarantine |
| `storage/interfaces.py` | What a store must do. The rest of the code only uses these |
| `storage/event_store.py`, `storage/parquet.py` | Parquet files through DuckDB (see `docs/adr/005`) |

**Try:** `python -m riskdetect.synthetic` then `python -m riskdetect.ingestion`, and read
the report it prints.

**Check yourself:** How does the same event sent twice get skipped? Where do rejected rows
go, and why keep them? What would you change to connect a new platform? (Answer: one
YAML file.)

---

## Session 3: Turning behavior into numbers (`features/`, about 1,000 lines)

The heart of the detector: 43 numbers per user, "as of" a moment.

| Read | What to look for |
|---|---|
| `features/windows.py` | Counting "in the last hour / day / week" without keeping full history |
| `features/state.py` | `ActorState`: each user's running summary, updated one event at a time |
| `features/families.py` | Every feature, with a one-line description. Unknown stays `None`, never 0 |
| `features/engine.py` | Applies events to states and computes features |
| `features/crowd.py` | The platform-wide memory behind coordination features: who links which site since when, who posted the same long message, who flooded a channel |
| `features/batch.py` | Daily snapshots, replaying history in time order (never seeing the future) |
| `features/normalization.py` | Percentiles per platform: "top 1%" means the same everywhere |

Features to study closely, because the real-data lessons are in them:
`rate_vs_baseline` (compared with the user's own past), `link_ratio_change_24h`,
`new_site_push_share_24h` (one new site pushed, not many different ones), and
`reply_share_7d` (does the user join conversations).

**Try:** `pytest tests/unit/features -q`, then read `tests/unit/features/test_features.py`:
each test is a tiny story with an obvious answer.

**Check yourself:** Why is "too few posts" `None` and not `0`? Why compare a user with
their *own* past? What is a leakage bug, and which test guards against it?

---

## Session 4: Judging (`rules/`, `models/`, `scoring/`, `explain/`, about 1,750 lines)

From numbers to a score, a tier and readable reasons.

| Read | What to look for |
|---|---|
| `configs/rules/*.yaml` | Every rule in plain YAML, in packs: `common` for every platform, `social`, `chat`, `marketplace`. Each platform file picks its packs (`rule_packs`). Read the comments: each says which real case it came from |
| `rules/conditions.py`, `rules/engine.py` | How conditions are checked; a missing value never triggers |
| `rules/rule.py` | Why a rule on account age alone is refused |
| `models/self_baseline.py` | "Different from your own past" (no training needed) |
| `models/population.py`, `models/isolation_forest.py` | "Unusual compared with others" (a weak signal) |
| `models/classifier.py`, `models/gbdt.py` | The learned model and its trust limits (`docs/adr/006`) |
| `configs/scoring.yaml`, `scoring/evidence.py`, `scoring/scorer.py` | Evidence combines; weak evidence alone stops below REVIEW; HIGH needs two pieces of evidence |
| `explain/reasons.py` | How each reason becomes a sentence |

**Try:** `python -m riskdetect.features` then `python -m riskdetect.scoring --top 5`.

**Check yourself:** Why can a brand-new account never be flagged for being new? What are
the four tiers and what does each recommend? Why is the learned model only "advisory" on
Reddit?

---

## Session 5: Live scoring and the website (`realtime/`, `serving/`, about 1,000 lines)

What runs when the server is on.

| Read | What to look for |
|---|---|
| `realtime/policy.py` | When a user is rescored: every 10 events, every 5 minutes, or at once for a scam link |
| `realtime/processor.py` | The live desk: the same feature code as the batch, so live and batch agree |
| `serving/service.py` | Everything the API offers, with no web framework inside |
| `serving/http.py` | The built-in web server: routes, the API key, demo mode, serving the dashboard |
| `serving/web/app.js` | The dashboard: queue, user page, chart, decision buttons |
| `Dockerfile`, `deploy/build_demo_data.sh` | How the public demo is packed (read before the Kubernetes weekend) |

**Try:** `python -m riskdetect.serving --platform reddit` and open http://127.0.0.1:8000/.

**Check yourself:** What does the server do on start, and why does it take time? What
is a reviewer's decision saved as? What does `--demo` switch off?

---

## Session 6: Knowing whether it works (`labels/`, `evaluation/`, `synthetic/`, `scenarios/`, about 3,400 lines)

How we test the detector itself, not just the code.

| Read | What to look for |
|---|---|
| `synthetic/personas.py` | The fake users, good and bad, including those copied from real data |
| `labels/outcomes.py` | The right answer for each snapshot (used only to mark, never to detect) |
| `evaluation/run.py`, `evaluation/gates.py` | The report card: split by time, compare with lazy shortcuts, pass/fail gates |
| `scenarios/library.py` | The 36 situations (including marketplace and coordination ones), each with its story and expected outcome; read the known gaps |
| `scenarios/behaviours.py` | How each kind of user acts, including the tricks of bad actors |

**Try:** `python -m riskdetect.scenarios` and read `data/reports/scenarios.md`.

**Check yourself:** Why are synthetic results "an upper bound"? What is a known gap, and
how does the test suite notice when one is fixed? Which gaps remain and why?

---

## Where to find the tests

Every package has tests under `tests/unit/<package>/`; whole-pipeline tests are in
`tests/integration/`. Reading a test next to its code is often the fastest way to
understand it. Run everything with `pytest -q` (about a minute).

## Real-data scripts

`scripts/stackexchange_to_jsonl.py` and `scripts/reddit_to_parquet.py` turn public dumps
into files an adapter can read. They are outside the package on purpose: the detector
itself never knows about Stack Exchange or Reddit.
