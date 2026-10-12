"""Group splits on unit (docs/16 §10.10). Notebook discipline reproduced verbatim.

GroupShuffleSplit/GroupKFold on `unit` with explicit overlap assertions — a cycle
from the same engine must never appear on both sides of a split.
"""

from __future__ import annotations


def group_shuffle_split(units: list[str], *, test_size: float, seed: int) -> tuple[list[str], list[str]]:
    import random

    rng = random.Random(seed)
    order = list(units)
    rng.shuffle(order)
    n_test = max(1, int(len(order) * test_size))
    test = set(order[:n_test])
    train = [u for u in order if u not in test]
    assert not (set(train) & test), "unit overlap between train and holdout"
    return train, sorted(test)


def group_kfold(units: list[str], *, n_splits: int, seed: int) -> list[tuple[list[str], list[str]]]:
    try:
        from sklearn.model_selection import GroupKFold
    except ImportError as exc:
        raise ImportError("train extra required: pip install 'rul[train]'") from exc
    import numpy as np

    # Clamp folds to the number of groups: dry-run (2 engines -> 1 train unit)
    # must not raise "n_splits=2 greater than n_samples=1".
    n_splits = max(1, min(n_splits, len(units)))
    if n_splits < 2:
        return []
    groups = np.array(units)
    X = np.zeros((len(units), 1))
    folds = []
    for tr, te in GroupKFold(n_splits=n_splits).split(X, groups=groups):
        folds.append(([units[i] for i in tr], [units[i] for i in te]))
    return folds


__all__ = ["group_shuffle_split", "group_kfold"]
