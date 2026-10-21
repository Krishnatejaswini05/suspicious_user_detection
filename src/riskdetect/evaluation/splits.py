"""Which snapshots prepare the detector, and which ones test it.

Always split by time, never randomly: a random split lets later data inform the
"preparation" of tests on earlier data, which is seeing the future. A platform
holdout tests whether what was prepared on some platforms works on an unseen one.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from riskdetect.features import PCT_SUFFIX, FeatureRow, fit_percentiles


def time_split(
    rows: Iterable[FeatureRow], cutoff: datetime
) -> tuple[list[FeatureRow], list[FeatureRow]]:
    """(snapshots before ``cutoff``, snapshots at or after it)."""
    before: list[FeatureRow] = []
    after: list[FeatureRow] = []
    for row in rows:
        (before if row["as_of"] < cutoff else after).append(row)
    return before, after


def last_days_cutoff(rows: Iterable[FeatureRow], days: int) -> datetime:
    """The cutoff that leaves the last ``days`` days of snapshots for testing."""
    latest: datetime = max(row["as_of"] for row in rows)
    return latest - timedelta(days=days - 1)


def platform_holdout(
    rows: Iterable[FeatureRow], platform: str
) -> tuple[list[FeatureRow], list[FeatureRow]]:
    """(snapshots from every other platform, snapshots from ``platform``)."""
    others: list[FeatureRow] = []
    held_out: list[FeatureRow] = []
    for row in rows:
        (held_out if row["platform"] == platform else others).append(row)
    return others, held_out


def refit_percentiles(
    platform: str, train: list[FeatureRow], test: list[FeatureRow]
) -> list[FeatureRow]:
    """Test rows with percentile columns fitted on the training rows only."""
    table = fit_percentiles(platform, train)
    cleaned = [{k: v for k, v in row.items() if not k.endswith(PCT_SUFFIX)} for row in test]
    return table.add_columns(cleaned)
