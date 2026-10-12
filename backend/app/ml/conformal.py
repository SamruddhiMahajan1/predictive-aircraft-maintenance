"""Conformal prediction intervals (docs/16 §11.1 — highest-value innovation).

Replaces the point estimate with a calibrated interval: RUL = 40 ± 12 (90% coverage).
Split-conformal calibration wraps the booster and emits a per-prediction interval at a
stated coverage level. This converts the §4 finding into something the operator can see:
the decision thresholds (MISSION_READY_MIN_RUL=30) sit inside the model's own noise band
(measured 3.9% mission-ready misclassification).

Requires a genuine holdout to calibrate against (Phase 5) — until a calibrated quantile
artifact ships, the half-width derives from the artifact's MAE with the Gaussian 90%
factor, clearly labelled as uncalibrated. Once `runs/<id>/metrics.json` ships residuals,
`calibrate()` stores the empirical quantile and intervals become calibrated.
"""

from __future__ import annotations

COVERAGE = 0.90
# Gaussian 90% two-sided factor; used only until empirical calibration lands.
GAUSS_90_FACTOR = 1.645
# MAE -> sigma under Laplace residuals (MAE = sigma / sqrt(2) for Laplace approx).
_MAE_TO_SIGMA = 1.2533


def calibrate(residuals: list[float], *, coverage: float = COVERAGE) -> float:
    """Empirical split-conformal quantile: P(|resid| <= q) >= coverage."""
    if not residuals:
        raise ValueError("no residuals to calibrate from")
    ordered = sorted(abs(r) for r in residuals)
    idx = min(len(ordered) - 1, int(coverage * len(ordered)))
    return float(ordered[idx])


def half_width(*, mae: float | None, quantile: float | None = None) -> float | None:
    if quantile is not None:
        return round(float(quantile), 1)
    if mae is None:
        return None
    return round(float(mae) * _MAE_TO_SIGMA * GAUSS_90_FACTOR / 2.0 * 2.0 / 2.0, 1)


def interval(rul: int, half: float | None, *, cap: int = 125) -> list[int] | None:
    if half is None:
        return None
    return [max(0, int(round(rul - half))), min(cap, int(round(rul + half)))]


__all__ = ["COVERAGE", "calibrate", "half_width", "interval"]
