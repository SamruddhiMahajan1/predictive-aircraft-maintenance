"""Training orchestration: features via contract, CV, holdout, refit (docs/16 §10.8).

- Baselines re-derived with the ONE MAD rule (no relative floor).
- Per-row regime z-scoring (build_matrix_per_row_regime).
- Real holdout by group, reported, THEN refit on 100% for serving — both numbers recorded.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any


def _seed_all(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass


def train_config(cfg, *, cmapss_dir, out_dir, dry_run: bool = False) -> dict:
    from ..data.loader import load_subset
    from .metrics import check_gates, mae, r2, rmse
    from .splits import group_shuffle_split

    _seed_all(cfg.seed)
    # Load + namespace units across subsets before any pooled split.
    pooled: dict[str, list[dict]] = {}
    for subset in cfg.datasets:
        units = load_subset(cmapss_dir, subset, kind="train", rul_cap=cfg.rul_cap)
        if dry_run:
            # PR-fast fixture: two engines prove the pipeline executes.
            for k in sorted(units)[:2]:
                pooled[k] = units[k]
            break
        pooled.update(units)
    if not pooled:
        raise ValueError("no training units loaded")
    names = sorted(pooled)
    train_names, holdout_names = group_shuffle_split(names, test_size=cfg.split.test_size, seed=cfg.seed)

    # Feature building + baselines are derived inside _fit_eval so dry-run and
    # full runs share the exact path (exam-style CV rebuilds features on
    # truncated histories — see evaluation/exam.py).
    from . import _fit as _fitmod  # local import: keeps rul importable without sklearn

    result = _fitmod.fit_and_evaluate(cfg, pooled, train_names, holdout_names, out_dir=out_dir)
    failures = check_gates(
        cv_rmse=result["cv_rmse_mean"],
        test_rmse=result["holdout_rmse"],
        mae_v=result["holdout_mae"],
        r2_v=result["holdout_r2"],
        gates=cfg.gates,
    )
    result["gate_failures"] = failures
    result["data_sha256"] = _hash_inputs(cmapss_dir, cfg.datasets)
    return result


def _hash_inputs(cmapss_dir, datasets) -> dict:
    from pathlib import Path

    out = {}
    d = Path(cmapss_dir)
    for subset in datasets:
        for kind in ("train", "test", "RUL"):
            p = d / f"{kind}_{subset}.txt"
            if p.exists():
                h = hashlib.sha256()
                with p.open("rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                out[f"{kind}_{subset}"] = h.hexdigest()
    return out


__all__ = ["train_config"]
