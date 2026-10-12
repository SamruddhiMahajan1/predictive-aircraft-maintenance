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

    groups = np.array(units)
    X = np.zeros((len(units), 1))
    folds = []
    for tr, te in GroupKFold(n_splits=n_splits).split(X, groups=groups):
        folds.append(([units[i] for i in tr], [units[i] for i in te]))
    return folds


__all__ = ["group_shuffle_split", "group_kfold"]
