"""The feature contract: the single definition of what a model input matrix is.

Pure standard library, no data, no model, no framework. The backend imports this
package; this package knows nothing about the backend, the database, or HTTP. That
one-way dependency is the point -- it is what makes it possible for training and
serving to share the transform instead of each keeping their own copy, which is how the
two drifted apart in the first place.

    from rul.contract import FEATURE_ORDER, build_matrix, robust_z
"""

from __future__ import annotations

from .errors import ContractError
from .matrix import ZScorer, build_matrix, build_matrix_per_row_regime, contract_widths, impute_s6
from .order import (
    DEFAULT_ROLLING_WINDOW,
    EXTRA_SENSORS,
    FEATURE_ORDER,
    MAX_WINDOW,
    MIN_WINDOW,
    POOLED_SENSORS,
    REGIME_COLUMN,
    ROLLING_DDOF,
    ROLLING_SENSORS,
    ROLLING_SUFFIXES,
    ROLLING_WINDOW,
    SENSORS,
    SETTINGS_COLUMNS,
    SPEC_SENSORS,
    contract_sensors,
)
from .regimes import classify_regime, regime_block
from .zscore import EPS_MAD, regime_z_scorer, robust_z

__all__ = [
    "ContractError",
    "EPS_MAD",
    "EXTRA_SENSORS",
    "POOLED_SENSORS",
    "DEFAULT_ROLLING_WINDOW",
    "FEATURE_ORDER",
    "MAX_WINDOW",
    "MIN_WINDOW",
    "REGIME_COLUMN",
    "ROLLING_DDOF",
    "ROLLING_SENSORS",
    "ROLLING_SUFFIXES",
    "ROLLING_WINDOW",
    "SENSORS",
    "SETTINGS_COLUMNS",
    "SPEC_SENSORS",
    "ZScorer",
    "build_matrix",
    "build_matrix_per_row_regime",
    "classify_regime",
    "contract_sensors",
    "contract_widths",
    "impute_s6",
    "regime_block",
    "regime_z_scorer",
    "robust_z",
]