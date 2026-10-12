"""XGBoost estimator factory. Hyperparameters come from config, never literals."""

from __future__ import annotations


def make_estimator(cfg, *, seed: int):
    try:
        from xgboost import XGBRegressor
    except ImportError as exc:
        raise ImportError("xgboost required: pip install xgboost") from exc
    kwargs: dict = {}
    # early_stopping_rounds requires an eval_set in fit(); the final refit on
    # 100% has no unbiased eval_set (rounds are pinned instead), so 0/None
    # must mean "disabled" rather than "stop immediately".
    if getattr(cfg, "early_stopping_rounds", 0):
        kwargs["early_stopping_rounds"] = cfg.early_stopping_rounds
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
        **kwargs,
    )


__all__ = ["make_estimator"]
