# ADR 006: Plain-Python models, and when a model may act on its own

Status: accepted

## Context

The detector adds learned and statistical models alongside the rules: an Isolation
Forest (unusual compared with others), a self-baseline check (unusual compared with the
user's own past) and a supervised boosted-trees classifier with isotonic calibration.

The development machine's application-control policy blocks native code: NumPy, and with
it scikit-learn, LightGBM and XGBoost, cannot load (see also ADR 005).

Evaluation, including a platform hold-out and a full live replay, showed that the models
can be confidently wrong in specific ways:

- ratios over two or three posts look extreme ("100% links" from one post);
- at the very start of observed data, everyone's weekly windows are nearly empty;
- on a platform it never trained on, the classifier made confident mistakes;
- trained on simulated data, the classifier learned simulator habits (e.g. "always the
  same site" = spam) that ordinary real users would trip.

## Decision

Models are written in plain Python (`models/`): Isolation Forest, gradient-boosted trees
with learned missing-value directions and per-prediction contributions, isotonic
calibration with interpolation between groups.

Trust rules, enforced in code:

1. **Ratios need examples.** A share of fewer than 3 posts is unknown (feature v2), and
   the classifier stays silent below 5 posts in the past week.
2. **No lifecycle inputs.** The classifier never sees account age, history length or
   evidence volume. Evidence volume drives confidence only.
3. **Unusual is not bad.** The population anomaly signal is weak: alone it reaches WATCH.
4. **New accounts are never judged against a past they do not have.** The self-baseline
   check needs 14+ days of history.
5. **A model trained elsewhere is advisory.** The classifier escalates on its own only on
   platforms it was calibrated on, and only when very sure (probability >= 0.9).
6. **One voice is not enough for HIGH.** HIGH needs at least two independent pieces of
   evidence (rules or models), unless a critical rule fired; otherwise a person reviews
   first.
7. **Fit on the past only.** Evaluation fits every model on the training period;
   `--holdout-platform` fits on the other platforms.
8. **Live starts after history.** Live replay reads a warm-up period of history before
   scoring, like connecting a real platform.

## Consequences

- No native dependencies; training the classifier takes ~15 s on the simulated month.
- Each fix above came from a measured false alarm; after them, no innocent user was
  flagged in the report cards, the platform hold-outs, or at any moment of the live replay.
- The models are slower than library versions and less battle-tested; they are covered by
  unit tests (combinations learned, contributions sum, calibration monotone, round trips).
- Simulated data limits what the classifier can learn honestly. Real labels are needed
  before trusting it more (e.g. lowering the 0.9 threshold).
