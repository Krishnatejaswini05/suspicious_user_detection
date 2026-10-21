"""Make model scores honest: among users scored 0.8, about 80% should really be bad.

Isotonic regression (pool-adjacent-violators, in plain Python): group raw scores so
that a higher raw score never gives a lower probability, fitted on examples the
model did not train on.

Between groups the result is *interpolated*, not stepped. Where the calibration
data has no examples (say, no raw scores between 0.12 and 0.99), a plain step
function would jump from "7%" straight to "100%", calling an uncertain 0.2 a
certainty. Interpolating keeps unseen middle scores in the middle.
"""

from collections.abc import Sequence
from typing import Any


class IsotonicCalibrator:
    def __init__(self) -> None:
        self.points: list[tuple[float, float]] = []  # (mean raw score, probability) per group

    def fit(
        self,
        scores: Sequence[float],
        labels: Sequence[int],
        weights: Sequence[float] | None = None,
    ) -> "IsotonicCalibrator":
        if not scores or len(scores) != len(labels):
            raise ValueError("need the same, non-zero number of scores and labels")
        w = list(weights) if weights is not None else [1.0] * len(scores)
        order = sorted(range(len(scores)), key=lambda i: scores[i])
        # Each group: [weighted positives, total weight, weighted raw-score sum]
        groups: list[list[float]] = []
        for i in order:
            groups.append([labels[i] * w[i], w[i], scores[i] * w[i]])
            while (
                len(groups) > 1 and groups[-2][0] / groups[-2][1] >= groups[-1][0] / groups[-1][1]
            ):
                top = groups.pop()
                for k in range(3):
                    groups[-1][k] += top[k]
        self.points = [(g[2] / g[1], g[0] / g[1]) for g in groups]
        return self

    def __call__(self, score: float) -> float:
        if not self.points:
            raise ValueError("fit the calibrator first")
        xs = [x for x, _ in self.points]
        if score <= xs[0]:
            return self.points[0][1]
        if score >= xs[-1]:
            return self.points[-1][1]
        low, high = 0, len(xs) - 1
        while high - low > 1:  # find the neighbors around score
            middle = (low + high) // 2
            if xs[middle] <= score:
                low = middle
            else:
                high = middle
        (x0, y0), (x1, y1) = self.points[low], self.points[high]
        return y0 if x1 == x0 else y0 + (y1 - y0) * (score - x0) / (x1 - x0)

    def to_dict(self) -> dict[str, Any]:
        return {"points": [list(point) for point in self.points]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IsotonicCalibrator":
        calibrator = cls()
        calibrator.points = [(float(x), float(y)) for x, y in data["points"]]
        return calibrator
