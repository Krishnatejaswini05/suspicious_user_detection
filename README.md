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
- Milestone 5: rules, scoring and explanations (`rules`, `scoring`, `explain`). Done.
- Milestone 6: realtime scoring (`riskdetect.realtime`). Done.
- Milestone 7: labels and evaluation (`riskdetect.labels`, `riskdetect.evaluation`). Done.
- Milestone 8: anomaly detection (`riskdetect.models`). Done.
- Milestone 9: trained classifier and calibration (`riskdetect.models`). Done.
- Milestone 10: API for other systems and a reviewer dashboard (`riskdetect.serving`). Done.
- Milestone 11: first real data (monero.stackexchange.com). Done.

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
python -m riskdetect.ingestion --data other/data --base-dir other   # data kept elsewhere
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

## Score users

```bash
python -m riskdetect.scoring                    # latest snapshot, every platform
```

Rules ([configs/rules/](configs/rules/), in packs by kind of platform: `common`, `social`,
`chat`, `marketplace`; each platform file picks its packs with `rule_packs`) fire on features; scoring
([configs/scoring.yaml](configs/scoring.yaml)) turns them into a score, a confidence
and a tier (LOW / WATCH / REVIEW / HIGH) with readable reasons and recommended actions.
Output: `data/scores/platform=<p>/scores.parquet`.

## Live scoring

```bash
python -m riskdetect.realtime                   # replay stored events through live scoring
```

Each event updates its user's running summary at once (the same code as the nightly
batch, so both agree). Users are rescored every 10 events or 5 minutes of activity, and
immediately for alarming events such as a link to a site in
[configs/lists/blocked_domains.txt](configs/lists/blocked_domains.txt). Every live score is
appended to `data/scores/history/`. In a deployment, `RealtimeProcessor.on_events` subscribes
to the ingestion publisher.

## Anomaly detection

```bash
python -m riskdetect.models                     # fit the models -> data/models/
```

Two detectors add evidence alongside the rules: a **self-baseline** check (an established
account suddenly behaving very differently from its own past; needs no training) and a
**population** Isolation Forest per platform (unusual compared with others; a weak signal
that alone can only reach WATCH). When labels exist it also trains a **classifier**:
plain-Python boosted trees with isotonic calibration, using behavior features only (never
account age). Scoring and live scoring load the models automatically. Trust rules (ratios
need examples, advisory on unseen platforms, HIGH needs two pieces of evidence) are in
[docs/adr/006-plain-python-models-and-trust.md](docs/adr/006-plain-python-models-and-trust.md).

## Reviewer dashboard and API

```bash
python -m riskdetect.serving                    # http://127.0.0.1:8000
python -m riskdetect.serving --platform reddit  # only some platforms: a faster start
```

Open the address in a browser for the **reviewer dashboard**: the queue of users waiting
for review (REVIEW and HIGH, most urgent first), each user's reasons and risk over time,
and buttons to record a decision (spam, bot, scam, hijacked, coordinated, or not
abusive). Each decision is saved as a label and takes the user out of the queue. Every
user page has its own link (`/#<platform>/<user>`). The dashboard is plain HTML and
JavaScript served by the same server, with nothing to install; it follows the system's
light or dark mode. On start, the server replays stored events to warm up (about 2.5
minutes for the 1.5 million Reddit events).

| Request | What it does |
|---|---|
| `POST /events` `{"platform", "records"}` | Send raw records; they are translated, stored and scored live |
| `GET /actors/{platform}/{actor_id}/risk` | Current score, tier, reasons, recommended actions |
| `GET /actors/{platform}/{actor_id}/history` | Scores over time (live scores, or else the daily runs) |
| `GET /review-queue?platform=&limit=` | Who a person should check, most urgent first |
| `POST /actors/{platform}/{actor_id}/review` `{"decision", "reviewer", "note"}` | Save a reviewer's verdict as a label for future training |
| `GET /platforms`, `GET /health` | What is connected and loaded |

Uses Python's built-in HTTP server (no extra libraries). Set `RISKDETECT_API_KEY` to require
an `X-API-Key` header; it refuses to listen beyond this computer without one. All logic is in
`DetectorService`, so another web framework can wrap it unchanged.

## Public demo (free hosting)

The `Dockerfile` builds a public demo: simulated users only (no real people), the
whole pipeline run at build time, and the dashboard served in demo mode (`--demo`: no
API key needed, sending events switched off, decisions kept only until restart).

```bash
docker build -t riskdetect-demo .
docker run -p 7860:7860 riskdetect-demo     # http://localhost:7860
```

On **Hugging Face Spaces** (free):

1. Create a Space: SDK **Docker**, template **Blank**, hardware **CPU basic** (free).
2. Upload the two files from [deploy/huggingface/](deploy/huggingface/) (`Dockerfile` and
   `README.md`) to the Space. The Dockerfile downloads this repository from GitHub.
3. Wait for the build (a few minutes). The Space sleeps when unused and wakes on the
   next visit; use "Factory rebuild" to pick up new commits.

Never publish real platform data this way: the dashboard names users as risky.

## Real data: a Stack Exchange site

Any Stack Exchange site from the public data dump can be connected with a YAML file
alone. [configs/platforms/stackexchange_monero.yaml](configs/platforms/stackexchange_monero.yaml)
does this for monero.stackexchange.com:

```bash
# 1. download monero.stackexchange.com.7z from the data dump and extract it into
#    data/raw/stackexchange_monero/extracted/ (data/ is not in git)
# 2. turn the XML into JSON lines (standard library only)
python -I scripts/stackexchange_to_jsonl.py data/raw/stackexchange_monero/extracted data/raw/stackexchange_monero
# 3. the usual pipeline
python -m riskdetect.ingestion --platform stackexchange_monero
python -m riskdetect.features --platform stackexchange_monero --days 3100   # the site's whole history
python -m riskdetect.models                                                # population model for this site
python -m riskdetect.scoring --platform stackexchange_monero --all-snapshots
```

The dump is licensed CC BY-SA; keep attribution with anything derived from it.

What the first real run showed (dump of 2024-12-31, about 33,000 events):

- All events loaded with no rejections and no code changes.
- The first scoring sent 7 established members to REVIEW, 4 of them highly trusted. All
  were legitimate: experts link to documentation a lot. The "sudden change" rule (R004)
  now compares a user with their own past instead of with the whole site. After that
  change: 0 REVIEW, 0 HIGH, and a few dozen users on WATCH, which is a soft signal only.
- Deleted posts are removed from the dump, so its spam votes cannot be tied to users. There
  are no real spam labels yet; the report card is still measured on synthetic data.
- Those trusted members are now simulated too (`expert_linker`, `maintainer`). The
  maintainer exposed one more gap: a day of "this page moved, see <docs>" replies still
  looked like a stolen account. Extra links now count only when they go to sites the user
  never linked before (`new_site_push_share_24h`), in R004 and in the self-baseline
  model. On the real site, the soft WATCH signals dropped from 35 users to 27.

## Real data: Reddit

[configs/platforms/reddit.yaml](configs/platforms/reddit.yaml) reads Reddit posts and
comments from the Arctic Shift archive (Hugging Face `open-index/arctic`, monthly Parquet
shards). Reddit content is subject to Reddit's terms; keep it local.

```bash
# 1. download comments_*.parquet and submissions_*.parquet shards into data/raw/reddit/download/
# 2. merge them into one export (DuckDB only)
python -I scripts/reddit_to_parquet.py data/raw/reddit/download data/raw/reddit
# 3. the usual pipeline
python -m riskdetect.ingestion --platform reddit
python -m riskdetect.features --platform reddit --days 62
python -m riskdetect.models
python -m riskdetect.scoring --platform reddit --all-snapshots
```

What the first run showed (November-December 2008: 1.5 million posts and comments from
87,000 users):

- All events loaded with no rejections and no code changes.
- The archive has no spam labels. The closest hint is Reddit's old guideline against
  self-promotion: accounts posting links to one website and almost never joining in.
- The first scoring caught copy-paste spam but missed most of these self-promoters: each
  post links to a different article, so they never repeat themselves. New rule R009
  (single-site self-promotion) uses a new feature, `reply_share_7d`.
- Reading flagged users' posts also found false alarms: keen sharers posting a different
  new website each time looked like stolen accounts. The "new site" feature now counts
  only links to the *one* new site pushed most (`new_site_push_share_24h`).
- After both changes, 1,235 users (1.4%) reached REVIEW or HIGH. A random sample of
  flagged users all promoted a single site. Because R009 resembles the self-promotion
  hint, the match with that hint (724 of 1,562 accounts) is partly circular; reading the
  posts is the real check. Low-volume self-promoters (under 10 posts a week) are missed.

## Scenario library (situations the detector must handle)

```bash
python -m riskdetect.scenarios                  # all scenarios -> data/reports/scenarios.md
python -m riskdetect.scenarios --only spam_ring
```

[src/riskdetect/scenarios/library.py](src/riskdetect/scenarios/library.py) lists 30
situations, each a small simulated world (a crowd plus the users under test) fed through
the same live scoring the server uses, with an expected outcome:

- **Innocent but unusual** (must never reach REVIEW): a big news day, a holiday binge, a
  power user, a keen link-sharer, an expert citing sources, a moderator's notices, a
  traveller changing time zones, a brand-new active member, a member returning after
  weeks away, a controversial member who is reported but widely answered; on a
  marketplace, a genuine new seller, a house clearance, a seller sharing a phone number
  for pickup, and a member who talks about Bitcoin every day.
- **Abuse** (must reach REVIEW within a stated time): a copy-paste bot, a known scam link,
  a sudden and a gradual account takeover, a bot disguised as a human, a slow spammer, a
  self-promoter, a comment spammer, a URL-shortener spammer, a spam ring, a reported
  spammer; on a marketplace, a fake seller (with and without payment talk) and a fake
  buyer who offers to overpay.

Situations the detector does not handle yet are marked as **known gaps** with the
reason (today: a gradual takeover, a disguised bot, a spam ring, and a moderator who is
not on the allowlist). They run as expected failures in the test suite, which notices
when one starts passing. Gaps closed so far:

- A stolen account's first burst was diluted by the owner's normal posts from earlier
  that day, so R001 now measures copying within the hour (`duplicate_ratio_1h`).
- Spam posted only as replies escaped R009, which assumes self-promoters never reply.
  New rule R010 (reply spam) covers it. Links to the platform's own pages (for example
  "see r/politics") are navigation, not promotion: a platform file lists them in
  `own_domains`, and the adapter leaves them out.
- A takeover eased in over a week made its own site look familiar after a day. A site
  now counts as new if the user never linked it before the last week. (A rule to catch
  the gradual takeover itself was tried and dropped: on real data it flagged a trusted
  Stack Exchange expert and ordinary Reddit users who had started linking GitHub or
  YouTube. See the known gap.)

The learned classifier is left out here on purpose: it is trained on the simulator, so it
would be tested against itself.

## Marketplace safety

Fake sellers and fake buyers give themselves away less by how much they post than by
what they ask for. Before discarding a message's text, the adapter notes two facts:

- **off-platform contact**: a phone number, an email, or "WhatsApp / Telegram / text me";
- **risky payment**: gift cards, crypto, wire transfers, cashier's cheques, "refund the
  difference" (English keywords only, for now).

A platform file may also map a **price** column. A listing is then compared with the usual
price in its category, learned only from other sellers' earlier listings.

| Rule | Fires on | Strength |
|---|---|---|
| R012 | Off-platform contact together with risky payment (a fake buyer's overpayment trick, a fake seller's "pay by gift card") | REVIEW |
| R013 | Two or more listings far below the usual price, with off-platform contact or risky payment | REVIEW or HIGH |
| R014 | Several listings far below the usual price, alone | weak (WATCH at most) |

Each strong rule needs two independent signs, because each sign alone is often innocent:
a seller leaves a phone number for pickup, someone moving house sells everything cheaply,
a crypto forum mentions Bitcoin constantly. The scenario library tests all of these.

Not covered yet: non-delivery reports from buyers (needs trade events), the same item
listed in many cities, and ratings from linked accounts (Milestone 12).

## Evaluate (the report card)

```bash
python -m riskdetect.evaluation                 # writes data/reports/evaluation.md
```

Tests on the last week of snapshots, with percentiles learned from earlier weeks only.
Reports precision, recall, false alarms per group (new accounts above all), live speed,
and a comparison with lazy shortcuts (random, age-only, volume-only). Exits with status 1
if any gate in [configs/evaluation.yaml](configs/evaluation.yaml) fails. Add
`--holdout-platform synthetic_market` to train the models on the other platforms only
(transfer test), or `--rules-only` to compare without models.

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
  rules/            readable YAML rules; never on account age alone; unknown never triggers
  scoring/          rules -> score, confidence, tier, actions (with fairness guardrails)
  explain/          readable reasons for every flag
  realtime/         live rescoring the moment users act; replay for measuring speed
  labels/           the right answers per snapshot; never read by the detector
  evaluation/       the report card: metrics, fairness by group, baselines, gates
  models/           anomaly detectors and the classifier, all plain Python
  serving/          the API: DetectorService + a built-in HTTP server
tests/              unit, integration and invariant tests
data/               local data (not in git)
```

Next milestones (a second real platform, coordinated groups, monitoring) are listed in the design doc.
