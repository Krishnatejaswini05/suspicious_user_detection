"""Gradient-boosted decision trees for yes/no questions, in plain Python.

Each small tree corrects the mistakes the trees before it still make: the first
gives a rough guess, the next focuses on what it got wrong, and so on. This learns
combinations of behaviors ("many copies AND few replies AND machine timing") that
single rules miss.

Implementation notes:
- Logistic loss with second-order (Newton) leaf values and L2 regularization.
- Features are binned into quantiles once, so split search scans histograms.
- Missing values are never imputed: each split learns which side "unknown" goes,
  so the model can treat "can't tell" differently from any real value.
- Per-prediction contributions (Saabas): how much each feature moved the score,
  used to explain the model in plain words.

Written here rather than taken from a library so it has no native dependencies
(see ADR 005: native libraries are blocked on the development machine).
"""

import math
import random
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

Value = float | None


def sigmoid(margin: float) -> float:
    if margin >= 0:
        return 1.0 / (1.0 + math.exp(-margin))
    exp = math.exp(margin)
    return exp / (1.0 + exp)


@dataclass(frozen=True)
class BoostingParams:
    n_trees: int = 100
    learning_rate: float = 0.1
    max_depth: int = 3
    min_child_weight: float = 1.0  # minimum hessian (roughly: rows) on each side of a split
    l2: float = 1.0
    n_bins: int = 32
    subsample: float = 0.8  # share of rows each tree learns from
    seed: int = 0


# A tree node: [value, feature, threshold, missing_left, left, right] or [value] for a leaf.
# "value" is the node's own prediction, kept on inner nodes too for explanations.
Node = list[Any]


class GradientBoostedTrees:
    def __init__(self, params: BoostingParams | None = None) -> None:
        self.params = params or BoostingParams()
        self.base_margin = 0.0
        self.trees: list[Node] = []
        self.n_features = 0

    # -- training --------------------------------------------------------------

    def fit(
        self,
        rows: Sequence[Sequence[Value]],
        labels: Sequence[int],
        weights: Sequence[float] | None = None,
    ) -> "GradientBoostedTrees":
        if not rows or len(rows) != len(labels):
            raise ValueError("need the same, non-zero number of rows and labels")
        p = self.params
        n = len(rows)
        self.n_features = len(rows[0])
        w = list(weights) if weights is not None else [1.0] * n
        positive = sum(wi for wi, yi in zip(w, labels, strict=True) if yi)
        total = sum(w)
        if positive in (0, total):
            raise ValueError("training needs both positive and negative examples")
        rate = positive / total
        self.base_margin = math.log(rate / (1 - rate))

        edges = [_quantile_edges([r[f] for r in rows], p.n_bins) for f in range(self.n_features)]
        columns = [[_bin(r[f], edges[f]) for r in rows] for f in range(self.n_features)]
        margins = [self.base_margin] * n
        rng = random.Random(p.seed)
        self.trees = []
        for _ in range(p.n_trees):
            probs = [sigmoid(m) for m in margins]
            grad = [wi * (pi - yi) for wi, pi, yi in zip(w, probs, labels, strict=True)]
            hess = [max(wi * pi * (1 - pi), 1e-12) for wi, pi in zip(w, probs, strict=True)]
            sample = [i for i in range(n) if rng.random() < p.subsample] or list(range(n))
            tree = self._grow(sample, columns, edges, grad, hess, depth=0)
            self.trees.append(tree)
            for i in range(n):
                margins[i] += _leaf_value(tree, rows[i])
        return self

    def _grow(
        self,
        index: list[int],
        columns: list[list[int]],
        edges: list[list[float]],
        grad: list[float],
        hess: list[float],
        depth: int,
    ) -> Node:
        p = self.params
        g_total = sum(grad[i] for i in index)
        h_total = sum(hess[i] for i in index)
        value = -g_total / (h_total + p.l2) * p.learning_rate
        if depth >= p.max_depth or h_total < 2 * p.min_child_weight:
            return [value]

        best = _best_split(index, columns, edges, grad, hess, g_total, h_total, p)
        if best is None:
            return [value]
        feature, bin_index, missing_left = best
        threshold = edges[feature][bin_index]
        column = columns[feature]
        left = [i for i in index if _goes_left(column[i], bin_index, missing_left)]
        right = [i for i in index if not _goes_left(column[i], bin_index, missing_left)]
        return [
            value,
            feature,
            threshold,
            missing_left,
            self._grow(left, columns, edges, grad, hess, depth + 1),
            self._grow(right, columns, edges, grad, hess, depth + 1),
        ]

    # -- prediction ------------------------------------------------------------

    def margin(self, row: Sequence[Value]) -> float:
        return self.base_margin + sum(_leaf_value(tree, row) for tree in self.trees)

    def predict_proba(self, row: Sequence[Value]) -> float:
        """Raw (uncalibrated) probability of the positive class."""
        return sigmoid(self.margin(row))

    def contributions(self, row: Sequence[Value]) -> list[float]:
        """How much each feature moved this row's margin (sums to margin - base)."""
        totals = [0.0] * self.n_features
        for tree in self.trees:
            node = tree
            while len(node) > 1:
                child = node[4] if _row_goes_left(node, row) else node[5]
                totals[node[1]] += child[0] - node[0]
                node = child
        # Each root's own value belongs to no feature; it is part of baseline().
        return totals

    def baseline(self) -> float:
        """Margin before any split: base plus every tree's root value."""
        return self.base_margin + sum(float(tree[0]) for tree in self.trees)

    # -- saving ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": self.params.__dict__,
            "base_margin": self.base_margin,
            "n_features": self.n_features,
            "trees": self.trees,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GradientBoostedTrees":
        model = cls(BoostingParams(**data["params"]))
        model.base_margin = data["base_margin"]
        model.n_features = data["n_features"]
        model.trees = data["trees"]
        return model


# -- helpers -------------------------------------------------------------------

_MISSING = -1


def _quantile_edges(values: Sequence[Value], n_bins: int) -> list[float]:
    """Up to n_bins - 1 split points at quantiles of the known values."""
    known = sorted(v for v in values if v is not None)
    if not known:
        return []
    edges: list[float] = []
    for k in range(1, n_bins):
        edge = known[min(len(known) - 1, k * len(known) // n_bins)]
        if not edges or edge > edges[-1]:
            edges.append(edge)
    return edges


def _bin(value: Value, edges: list[float]) -> int:
    """Bin k holds values with edges[k-1] <= value < edges[k]; missing values get -1."""
    return _MISSING if value is None else bisect_right(edges, value)


def _goes_left(bin_value: int, split_bin: int, missing_left: bool) -> bool:
    """Left side: values below edges[split_bin], i.e. bins 0..split_bin."""
    if bin_value == _MISSING:
        return missing_left
    return bin_value <= split_bin


def _row_goes_left(node: Node, row: Sequence[Value]) -> bool:
    value = row[node[1]]
    if value is None:
        return bool(node[3])
    return value < float(node[2])


def _leaf_value(tree: Node, row: Sequence[Value]) -> float:
    node = tree
    while len(node) > 1:
        node = node[4] if _row_goes_left(node, row) else node[5]
    return float(node[0])


def _best_split(
    index: list[int],
    columns: list[list[int]],
    edges: list[list[float]],
    grad: list[float],
    hess: list[float],
    g_total: float,
    h_total: float,
    p: BoostingParams,
) -> tuple[int, int, bool] | None:
    def score(g: float, h: float) -> float:
        return g * g / (h + p.l2)

    parent = score(g_total, h_total)
    best_gain, best = 1e-9, None
    for feature, column in enumerate(columns):
        n_edges = len(edges[feature])
        if n_edges == 0:
            continue
        g_bins = [0.0] * (n_edges + 1)
        h_bins = [0.0] * (n_edges + 1)
        g_missing = h_missing = 0.0
        for i in index:
            b = column[i]
            if b == _MISSING:
                g_missing += grad[i]
                h_missing += hess[i]
            else:
                g_bins[b] += grad[i]
                h_bins[b] += hess[i]
        g_left = h_left = 0.0
        for split_bin in range(n_edges):  # left = bins 0..split_bin, i.e. value < edges[split_bin]
            g_left += g_bins[split_bin]
            h_left += h_bins[split_bin]
            for missing_left in (False, True):
                gl = g_left + (g_missing if missing_left else 0.0)
                hl = h_left + (h_missing if missing_left else 0.0)
                gr, hr = g_total - gl, h_total - hl
                if hl < p.min_child_weight or hr < p.min_child_weight:
                    continue
                gain = score(gl, hl) + score(gr, hr) - parent
                if gain > best_gain:
                    best_gain, best = gain, (feature, split_bin, missing_left)
    return best
