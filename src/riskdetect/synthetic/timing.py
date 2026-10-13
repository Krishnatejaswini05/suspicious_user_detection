"""When simulated users act.

Humans: a few sessions a day during their own waking hours, with irregular gaps.
Bots: bursts at near-fixed intervals, at any hour of day or night.
"""

import math
import random
from datetime import datetime, timedelta

from riskdetect.synthetic.personas import BotHabits

_MIN_GAP_SECONDS = 5.0
_MEAN_GAP_SECONDS = 90.0
_WAKING_HOURS = 15.0


def poisson(rng: random.Random, mean: float) -> int:
    """Random count with the given average (Knuth's method; fine for small means)."""
    if mean <= 0:
        return 0
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


def human_day(
    rng: random.Random,
    day_start_utc: datetime,
    utc_offset: timedelta,
    wake_hour: float,
    sessions_per_day: float,
    actions_per_session: float,
) -> list[datetime]:
    """Action times for one local day: sessions within waking hours, irregular gaps."""
    local_midnight_utc = day_start_utc - utc_offset
    times: list[datetime] = []
    for _ in range(poisson(rng, sessions_per_day)):
        hour = wake_hour + rng.uniform(0, _WAKING_HOURS)
        moment = local_midnight_utc + timedelta(hours=hour)
        for _ in range(1 + poisson(rng, max(actions_per_session - 1, 0))):
            times.append(moment)
            gap = max(_MIN_GAP_SECONDS, rng.expovariate(1 / _MEAN_GAP_SECONDS))
            moment += timedelta(seconds=gap)
    return times


def bot_day(
    rng: random.Random,
    day_start_utc: datetime,
    habits: BotHabits,
    bursts_per_day: float,
    interval_seconds: float,
) -> list[datetime]:
    """Action times for one day of automated bursts, at any hour."""
    times: list[datetime] = []
    for _ in range(poisson(rng, bursts_per_day)):
        moment = day_start_utc + timedelta(hours=rng.uniform(0, 24))
        for _ in range(rng.randint(*habits.burst_size)):
            times.append(moment)
            moment += timedelta(seconds=interval_seconds * rng.uniform(0.9, 1.1))
    return times
