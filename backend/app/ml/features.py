"""Serving-path adapter over `rul.contract`.

This module used to *be* the contract -- the feature transform lived here and was
duplicated in the training notebook, and the two copies drifted by a single constant
(`MAD_REL_FLOOR`), which silently zeroed the `s8` and `s13` inputs and pinned the `fan`
component to perfect health forever. See docs/16 §3.1 C2 and C3.

The transform now lives in `ml/src/rul/contract/`, which training and serving both
import, so there is only one copy that can disagree with itself. This file keeps the
names the rest of `app/ml` imports, and translates between the two error types: the
contract raises `ContractError` (it must not know the backend exists), and the backend
raises `BusinessRuleError` for the cases it owns.

Window -> feature matrix. Order is asserted against the feature contract.

The contract is whatever the trained model declares -- 29 columns for the FD001 models
(docs/08 §3.2):

    op1, op2                                  2   operating settings
    s2..s21 (15, s6 included)                15   sensors
    <sensor>_rollmean5 / _rollstd5 x 6        12   rolling mean AND std

`cycle` is deliberately NOT an input. It correlates with RUL only because the official
test set is truncated early, so feeding it produces a model that scores well and fails on
real data. It is still tracked per aircraft, for the fallback and for provenance.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from rul.contract import (
    FEATURE_ORDER,
    MAX_WINDOW,
    MIN_WINDOW,
    REGIME_COLUMN,
    ROLLING_SENSORS,
    ROLLING_SUFFIXES,
    ROLLING_WINDOW,
    SENSORS,
    SETTINGS_COLUMNS,
    SPEC_SENSORS,
    ContractError,
    build_matrix,
    classify_regime,
    contract_sensors,
    impute_s6,
    regime_block,
    robust_z,
)
from rul.contract import regime_z_scorer as _regime_z_scorer

from ..core.errors import BusinessRuleError

# `rul` ships no py.typed marker of its own yet; without this mypy treats every symbol
# imported from it as `Any`, which silently disables checking of this module's own
# return types and rejects the `_ContractFailure` subclass below. Adding the marker to
# `ml/pyproject.toml` is the real fix (see ci.yml, which type-checks the contract); this
# keeps `mypy app/ml` honest until that runs.

# `MAD_REL_FLOOR` is deliberately gone. It read `max(abs(median) * 1e-4, eps)` where
# training read `max(mad, 1e-6)`, and the difference zeroed `s8`/`s13` -- see the module
# docstring. Anything still importing it is reading a rule the model was not trained on;
# re-adding it re-breaks the `fan` component, and tests/unit/test_features.py and
# tests/ml/test_model_quality.py are written to fail loudly if that happens.


class _ContractFailureError(BusinessRuleError, ContractError):
    """A contract rejection surfaced as a backend domain error.

    Raised by the wrappers below so that `app/ml/inference.py` can keep catching the
    backend's own type, while the contract itself stays independent of this package.
    Multiple inheritance is used rather than a `raise ... from` chain because callers
    through `app/api` map `BusinessRuleError` onto a 422; an adapter that converted in
    one direction only would silently change those responses to 500.
    """


def build_window(
    window: list[dict[str, Any]],
    *,
    s6_median: float,
    absolute_cycles: list[int] | None = None,
    feature_order: Sequence[str] = FEATURE_ORDER,
    sensors_to_z: Callable[[dict[str, float]], dict[str, float]] | None = None,
    regime_global: int = 0,
    regime_column: str = REGIME_COLUMN,
    missing_sensor_values: dict[str, float] | None = None,
) -> tuple[list[list[float]], set[str]]:
    """Build the model matrix for a window. See `rul.contract.build_matrix`.

    Returns (matrix, imputed_sensors) where `imputed_sensors` names each sensor that
    was filled rather than measured. It is a set, not the `bool` this used to return:
    a bool was `True` on essentially every request, because `s6` and `s10`/`s16` are
    absent from ordinary FD001 telemetry, so it carried no signal at all.
    """
    try:
        return build_matrix(
            window,
            s6_median=s6_median,
            absolute_cycles=absolute_cycles,
            feature_order=feature_order,
            sensors_to_z=sensors_to_z,
            regime_global=regime_global,
            regime_column=regime_column,
            missing_sensor_values=missing_sensor_values,
        )
    except ContractError as exc:
        raise _ContractFailureError(str(exc)) from exc


def regime_z_scorer(
    stats: dict[str, Any],
    regime: int = 0,
    *,
    subset: str | None = None,
    eps: float = 1e-6,
    sensors: Sequence[str] | None = None,
) -> Callable[[dict[str, float]], dict[str, float]]:
    """Contract z-scorer, re-raising a missing baseline as a backend domain error.

    This shadows the contract's `regime_z_scorer` on purpose. Everything inside the
    backend catches `BusinessRuleError` -- which maps to a 422 -- so the adapter has to
    raise that; `inference.predict` additionally catches `ContractError`, which the
    adapter's exception satisfies too.
    """
    try:
        return _regime_z_scorer(stats, regime, subset=subset, eps=eps, sensors=sensors)
    except ContractError as exc:
        raise _ContractFailureError(str(exc)) from exc


__all__ = [
    "SPEC_SENSORS",
    "SENSORS",
    "ROLLING_SENSORS",
    "ROLLING_WINDOW",
    "ROLLING_SUFFIXES",
    "SETTINGS_COLUMNS",
    "REGIME_COLUMN",
    "MIN_WINDOW",
    "MAX_WINDOW",
    "FEATURE_ORDER",
    "contract_sensors",
    "impute_s6",
    "build_window",
    "regime_z_scorer",
    "regime_block",
    "classify_regime",
    "robust_z",
    "ContractError",
]