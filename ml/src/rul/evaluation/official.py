"""Official-test scoring: final cycle per engine vs RUL_FDxxx.txt (docs/16 §4).

The harness that reproduced the shipped artifact's RMSE 17.942 / MAE 13.079 to
three decimals lives here — same semantics, same ground truth.
"""

from __future__ import annotations

from ..modeling.metrics import mae, rmse


def score_official(y_true: list[float], y_pred: list[float]) -> dict:
    return {"rmse": rmse(y_true, y_pred), "mae": mae(y_true, y_pred), "n": len(y_true)}


__all__ = ["score_official"]
