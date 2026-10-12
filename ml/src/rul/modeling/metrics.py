"""Metric definitions + gate checks (docs/08:524-527, docs/16 §6).

MAE ≤ 14, RMSE ≤ 20, R² ≥ 0.80 — evaluated against MEASURED predictions, never
against the notebook's own JSON.
"""

from __future__ import annotations

import math


def rmse(y_true: list[float], y_pred: list[float]) -> float:
    return math.sqrt(sum((p - t) ** 2 for p, t in zip(y_true, y_pred)) / max(1, len(y_true)))


def mae(y_true: list[float], y_pred: list[float]) -> float:
    return sum(abs(p - t) for p, t in zip(y_true, y_pred)) / max(1, len(y_true))


def r2(y_true: list[float], y_pred: list[float]) -> float:
    mean = sum(y_true) / max(1, len(y_true))
    ss_tot = sum((t - mean) ** 2 for t in y_true)
    ss_res = sum((p - t) ** 2 for p, t in zip(y_pred, y_true))
    return 1 - ss_res / ss_tot if ss_tot else 0.0


def check_gates(*, cv_rmse: float, test_rmse: float, mae_v: float, r2_v: float, gates) -> list[str]:
    failures = []
    if cv_rmse > gates.max_cv_rmse:
        failures.append(f"cv_rmse {cv_rmse:.3f} > {gates.max_cv_rmse}")
    if test_rmse > gates.max_test_rmse:
        failures.append(f"test_rmse {test_rmse:.3f} > {gates.max_test_rmse}")
    if mae_v > gates.max_mae:
        failures.append(f"mae {mae_v:.3f} > {gates.max_mae}")
    if r2_v < gates.min_r2:
        failures.append(f"r2 {r2_v:.3f} < {gates.min_r2}")
    return failures


__all__ = ["rmse", "mae", "r2", "check_gates"]
