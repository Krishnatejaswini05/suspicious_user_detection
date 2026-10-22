"""Self-baseline anomaly: is this user acting very differently from how they usually act?

Aimed at taken-over accounts: years of normal behavior, then suddenly link-heavy,
repetitive posting, far more of it, at unusual hours.

Only established accounts are judged: a user needs at least two weeks of observed
history and a few past posts before there is a "usual" to differ from. New
accounts get no signal at all from this detector, ever.

The change score multiplies two parts, so both must be present:
- *what* they post changed: links or repeats up sharply versus their own past, by at
  least a few posts (a ratio over two or three posts is not evidence). Extra links
  count only as far as they push one site the user never linked before: a maintainer
  pointing many threads at the usual documentation, or a keen sharer posting a different
  new site each time, is not a thief pushing their site;
- *how* they post changed: much more activity than usual. Activity at hours never
  used before supports this at half weight only: people with one or two short
  sessions a day often drift to a new hour, so on its own it means little.
A busy day alone, or a couple of unusual posts alone, is not enough.
"""

import math
from collections.abc import Mapping
from typing import Any

from riskdetect.scoring.evidence import Signal

CODE = "M002_self_baseline_change"
MIN_HISTORY_DAYS = 14
MIN_POSTS_24H = 5  # ratios over the last day need a few posts behind them
STRONG_FROM = 0.4  # change score at which the signal becomes strong
MIN_EXCESS_POSTS = 4  # a content change needs at least this many more such posts than usual
NEW_HOURS_WEIGHT = 0.5
_RATE_FOR_FULL_CHANGE = 10.0  # 10x the usual activity counts as a complete change


def _get(row: Mapping[str, Any], name: str) -> float | None:
    value = row.get(name)
    return None if value is None else float(value)


def change_score(row: Mapping[str, Any]) -> float | None:
    """0 = behaving as usual; towards 1 = very different from their own past. None = can't tell."""
    history = _get(row, "history_days")
    posts = _get(row, "posts_24h")
    if history is None or history < MIN_HISTORY_DAYS or posts is None or posts < MIN_POSTS_24H:
        return None

    content_shift = 0.0
    new_sites = _get(row, "new_site_push_share_24h") or 0.0  # unknown never adds
    for recent, before, weight in (
        ("link_ratio_24h", "link_ratio_before", new_sites),
        ("duplicate_ratio_24h", "duplicate_ratio_before", 1.0),
    ):
        now, then = _get(row, recent), _get(row, before)
        if now is None or then is None:
            continue
        shift = now - then
        if shift * posts >= MIN_EXCESS_POSTS:  # enough extra posts behind the ratio
            content_shift = max(content_shift, shift * weight)

    rate = _get(row, "rate_vs_baseline")
    rate_shift = 0.0
    if rate is not None and rate > 1:
        rate_shift = min(1.0, math.log(rate) / math.log(_RATE_FOR_FULL_CHANGE))
    new_hours = _get(row, "new_hours_share_24h") or 0.0
    behavior_shift = max(rate_shift, NEW_HOURS_WEIGHT * new_hours)

    return round(max(0.0, content_shift) * behavior_shift, 4)


class SelfBaselineAnomaly:
    """Needs no training: each user is compared only with their own past."""

    name = "self_baseline"

    def signals(self, row: Mapping[str, Any]) -> list[Signal]:
        score = change_score(row)
        if score is None or score < STRONG_FROM / 2:
            return []
        strong = score >= STRONG_FROM
        strength = round(min(0.85, 0.5 + 0.4 * score) if strong else 0.25, 4)
        parts = []
        for recent, before, label in (
            ("link_ratio_24h", "link_ratio_before", "posts with links"),
            ("duplicate_ratio_24h", "duplicate_ratio_before", "repeated posts"),
        ):
            now, then = _get(row, recent), _get(row, before)
            if now is not None and then is not None and now - then >= 0.3:
                parts.append(f"{label} {now:.0%} in the last day vs {then:.0%} usually")
        new_sites = _get(row, "new_site_push_share_24h")
        if new_sites:
            parts.append(f"{new_sites:.0%} of recent links push one site never linked before")
        rate = _get(row, "rate_vs_baseline")
        if rate is not None and rate >= 2:
            parts.append(f"{rate:.1f}x the usual activity")
        new_hours = _get(row, "new_hours_share_24h")
        if new_hours:
            parts.append(f"{new_hours:.0%} of recent activity at hours never used before")
        return [
            Signal(
                code=CODE,
                source=f"model:{self.name}",
                category="hijacked",
                strength=strength,
                strong=strong,
                reason="Behaving very differently from this account's own past: "
                + "; ".join(parts or ["several behaviors changed at once"]),
                evidence={"change_score": score},
            )
        ]
