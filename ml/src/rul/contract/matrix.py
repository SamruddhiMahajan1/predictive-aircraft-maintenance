"""Window -> feature matrix. The rolling transform, in one place.

Pure standard library: the matrix is built with plain Python arithmetic rather than numpy
so that the serving path and the training path call the *same* function and cannot drift.
That was the entire point of the extraction -- the transform used to exist twice, once in
the notebook and once here, and had already diverged by a constant.

Two preprocessing variants exist, and the difference matters:

    scaler variant   Phase 1 FD001 model -- raw sensors here, StandardScaler applied to
                     the finished matrix by the model store.
    z-score variant  Phase 2 models -- each sensor is standardised against its own
                     regime's healthy baseline BEFORE the rolling statistics are taken,
                     because a rolling mean of raw values is not the same feature as a
                     rolling mean of z-scores once more than one regime is involved.

`sensors_to_z` selects between them; passing None gives the raw (scaler) path.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .errors import ContractError
from .order import (
    DEFAULT_ROLLING_WINDOW,
    FEATURE_ORDER,
    MAX_WINDOW,
    MIN_WINDOW,
    REGIME_COLUMN,
    ROLLING_DDOF,
    SENSORS,
    SETTINGS_COLUMNS,
    contract_sensors,
)

ZScorer = Callable[[dict[str, float]], dict[str, float]]


def impute_s6(row: dict[str, Any], s6_median: float) -> tuple[dict[str, float], bool]:
    """Spec item 45 lists 14 sensors; the trained model also uses s6."""
    sensors = dict(row.get("sensors") or {})
    if sensors.get("s6") is None:
        sensors["s6"] = s6_median
        return sensors, True
    return sensors, False


def build_matrix(
    window: list[dict[str, Any]],
    *,
    s6_median: float,
    absolute_cycles: list[int] | None = None,
    feature_order: Sequence[str] = FEATURE_ORDER,
    sensors_to_z: ZScorer | None = None,
    regime_global: int = 0,
    regime_column: str = REGIME_COLUMN,
    missing_sensor_values: dict[str, float] | None = None,
) -> tuple[list[list[float]], set[str]]:
    """Build the model matrix for a window.

    Returns (matrix, imputed). Raises ContractError on a window too short to carry a
    rolling statistic. `regime_global` is written only when the contract asks for that
    column, so the 29-feature FD001 contract is unaffected.

    The base sensors come from `feature_order`, not from SENSORS. A sensor the contract
    wants but the telemetry lacks is filled from `missing_sensor_values` (its healthy
    median, so the derived z-score is exactly 0.0) and counted as imputed: `s10`/`s16`
    are constant in FD001, so FD001 telemetry does not carry them at all and the pooled
    booster still expects the columns. Filling rather than dropping keeps the matrix
    positionally aligned with the booster, which is the whole point.

    The second element of the return tuple is a per-sensor mapping, not a bare bool. A
    single bool was always true in practice -- `s6` and `s10`/`s16` are absent from
    ordinary FD001 telemetry -- so the flag carried no information and the documented
    "the frontend cannot emit sensor_6, so accuracy suffers" signal could never appear.
    """
    if len(window) < MIN_WINDOW:
        raise ContractError(
            f"window must contain at least {MIN_WINDOW} cycles, got {len(window)}"
        )
    window = window[-MAX_WINDOW:]

    cycles = absolute_cycles or [int(r.get("cycle", i + 1)) for i, r in enumerate(window)]
    needed = contract_sensors(feature_order)
    imputed: set[str] = set()
    series: list[dict[str, float]] = []
    # `cycles` is zipped in only for the strict length check against `window`; the
    # per-row cycle number is not an input (see order.py).
    for row, _cycle in zip(window, cycles, strict=True):
        sensors, s6_was_imputed = impute_s6(row, s6_median)
        if s6_was_imputed:
            imputed.add("s6")
        values: dict[str, float] = {}
        for sensor in needed:
            raw = sensors.get(sensor)
            if raw is None:
                # constant in this subset, so never measured; pinned to its healthy
                # median, which is the value the booster was trained to see as z=0
                values[sensor] = float((missing_sensor_values or {}).get(sensor, 0.0))
                imputed.add(sensor)
            else:
                values[sensor] = float(raw)
        settings = row.get("settings") or {}
        values["op1"] = float(settings.get("setting_1", settings.get("op1", 0.0)))
        values["op2"] = float(settings.get("setting_2", settings.get("op2", 0.0)))
        # z-score each cycle BEFORE any rolling statistic is derived from it
        if sensors_to_z is not None:
            values.update(sensors_to_z(values))
        # A pooled (multi-subset) contract carries a 30th column, `regime_global`.
        # The absolute id is what the booster was trained on -- each subset's regime
        # ids are offset so FD002's regime 0 cannot collide with FD001's -- so the
        # offset must be applied here rather than by the caller. Written into every
        # cycle of the window: it is constant across an engine in single-regime data,
        # but in six-regime data consecutive cycles can sit in different conditions,
        # so it is computed per cycle by the caller-supplied classifier in predict().
        if regime_column in feature_order:
            values[regime_column] = float(regime_global)
        series.append(values)

    # `feature_order` contains derived (rolling) names that are not keys of `series`,
    # so index only the columns that exist; the rest are computed in the loop below.
    columns = {
        name: [r[name] for r in series]
        for name in feature_order
        if name in series[0]
    }
    matrix: list[list[float]] = []
    for i in range(len(series)):
        row_out: list[float] = []
        for name in feature_order:
            if "_roll" in name:
                sensor, rest = name.split("_roll", 1)
                is_mean = rest.startswith("mean")
                width = _window_for(name)
                start = max(0, i - width + 1)
                chunk = columns[sensor][start : i + 1]
                if is_mean:
                    row_out.append(sum(chunk) / len(chunk))
                else:
                    if len(chunk) < 2:
                        # A single sample has no spread to report. Training wrote 0.0
                        # here rather than NaN, so NaN would be a new input value.
                        row_out.append(0.0)
                    else:
                        m = sum(chunk) / len(chunk)
                        denom = len(chunk) - ROLLING_DDOF
                        var = sum((v - m) ** 2 for v in chunk) / denom
                        row_out.append(var ** 0.5)
            else:
                row_out.append(columns[name][i])
        matrix.append(row_out)

    # guards the silent-misprediction failure mode
    assert len(matrix[0]) == len(feature_order), (
        f"built {len(matrix[0])} columns, contract declares {len(feature_order)}"
    )
    return matrix, imputed


def _window_for(name: str) -> int:
    """The trailing window a derived column name declares, e.g. `s4_rollmean5` -> 5.

    Read from the name rather than assumed, so a contract that declares a different
    rolling width is honoured instead of silently measured at 5.
    """
    digits = "".join(c for c in name.rsplit("_", 1)[-1] if c.isdigit())
    return int(digits) if digits else DEFAULT_ROLLING_WINDOW


def contract_widths(feature_order: Sequence[str]) -> dict[str, int]:
    """Map each derived column name to the window it uses."""
    return {n: _window_for(n) for n in feature_order if "_roll" in n}


__all__ = [
    "build_matrix",
    "impute_s6",
    "contract_widths",
    "ZScorer",
    "SENSORS",
    "SETTINGS_COLUMNS",
]