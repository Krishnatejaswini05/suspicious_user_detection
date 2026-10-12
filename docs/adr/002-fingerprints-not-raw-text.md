# ADR 002: Store text fingerprints, not raw text

Status: accepted

## Context

Content signals matter for spam (copy-paste posting, repeated links), but storing what
users wrote creates privacy, security and legal risk, especially for private messages.

## Decision

Adapters reduce text to:

- `text_hash` — exact-match fingerprint (lowercase hex digest);
- `simhash` — near-duplicate fingerprint (64-bit);
- `length`, `language`, `url_domains` (domains only), `mention_count`.

Raw text is discarded inside the adapter. `text_hash` must be a hex digest, which also
catches raw text being mapped there by mistake. Links are never visited.

## Alternatives

- Store raw text: most flexible, highest risk. Possible later as an explicit
  per-platform opt-in (`store_raw_text`) where the operator owns the data.
- Embeddings: capture meaning (reworded scams). Planned as a later addition.

## Consequences

- Exact and near-duplicate spam is detectable; meaning-based abuse is not, until
  embeddings are added.
- Content features cannot be recomputed with new text processing on old data.
