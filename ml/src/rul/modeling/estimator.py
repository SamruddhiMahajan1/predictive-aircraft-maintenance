"""XGBoost estimator factory. Hyperparameters come from config, never literals."""

from __future__ import annotations


def make_estimator(cfg, *, seed: int):
    try:
        from xgboost import XGBRegressor
    except ImportError as exc:
        raise ImportError("xgboost required: pip install xgboost") from exc
    return XGBRegressor(
        n_estimators=cfg.n_estimators,
        learning_rate=cfg.learning_rate,
        max_depth=cfg.max_depth,
        min_child_weight=cfg.min_child_weight,
        subsample=cfg.subsample,
        colsample_bytree=cfg.colsample_bytree,
        reg_lambda=cfg.reg_lambda,
        random_state=seed,
        n_jobs=-1,
        tree_method="hist",
    )


__all__ = ["make_estimator"]
