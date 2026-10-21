"""Isolation Forest, in plain Python.

The idea: to single out one point, keep splitting the data at random. Points in a
dense crowd need many splits; unusual points stand apart and are isolated in a few.
Averaged over many random trees, a short path means "unusual".

Written here rather than taken from a library so it has no native dependencies
(see ADR 005: native libraries can be blocked on the development machine).
Reference: Liu, Ting and Zhou, "Isolation Forest" (ICDM 2008).
"""

import math
import random
from collections.abc import Sequence
from typing import Any

_EULER = 0.5772156649

Tree = Any  # nested lists: [feature, split, left, right] for a split, [size] for a leaf


def average_path(n: int) -> float:
    """Expected path length of an unsuccessful search in a random binary tree of n points."""
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2.0 * (math.log(n - 1) + _EULER) - 2.0 * (n - 1) / n


class IsolationForest:
    def __init__(self, n_trees: int = 50, sample_size: int = 256, seed: int = 0) -> None:
        if n_trees < 1 or sample_size < 2:
            raise ValueError("need at least 1 tree and a sample size of at least 2")
        self.n_trees = n_trees
        self.sample_size = sample_size
        self.seed = seed
        self.trees: list[Tree] = []
        self._sample_used = sample_size

    def fit(self, rows: Sequence[Sequence[float]]) -> "IsolationForest":
        if not rows:
            raise ValueError("cannot fit on no rows")
        rng = random.Random(self.seed)
        size = min(self.sample_size, len(rows))
        limit = math.ceil(math.log2(max(size, 2)))
        self._sample_used = size
        self.trees = [
            _grow(rng, rng.sample(list(rows), size), 0, limit) for _ in range(self.n_trees)
        ]
        return self

    def score(self, row: Sequence[float]) -> float:
        """Anomaly score in (0, 1): around 0.5 is ordinary; towards 1 is unusual."""
        if not self.trees:
            raise ValueError("fit the forest before scoring")
        mean_path = sum(_path(tree, row, 0) for tree in self.trees) / len(self.trees)
        return math.pow(2.0, -mean_path / average_path(self._sample_used))

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_trees": self.n_trees,
            "sample_size": self.sample_size,
            "seed": self.seed,
            "sample_used": self._sample_used,
            "trees": self.trees,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IsolationForest":
        forest = cls(data["n_trees"], data["sample_size"], data["seed"])
        forest.trees = data["trees"]
        forest._sample_used = data["sample_used"]
        return forest


def _grow(rng: random.Random, rows: list[Sequence[float]], depth: int, limit: int) -> Tree:
    if depth >= limit or len(rows) <= 1:
        return [len(rows)]
    width = len(rows[0])
    splittable = [f for f in range(width) if min(r[f] for r in rows) < max(r[f] for r in rows)]
    if not splittable:
        return [len(rows)]  # all remaining points are identical
    feature = rng.choice(splittable)
    low = min(r[feature] for r in rows)
    high = max(r[feature] for r in rows)
    split = rng.uniform(low, high)
    left = [r for r in rows if r[feature] < split]
    right = [r for r in rows if r[feature] >= split]
    return [feature, split, _grow(rng, left, depth + 1, limit), _grow(rng, right, depth + 1, limit)]


def _path(node: Tree, row: Sequence[float], depth: int) -> float:
    while len(node) == 4:
        feature, split, left, right = node
        node = left if row[feature] < split else right
        depth += 1
    return depth + average_path(node[0])
