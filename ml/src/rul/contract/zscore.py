"""The one robust z-score rule, in one place.

There used to be two of these -- one in the training notebook, one in the serving code --
and they disagreed by a single constant. The serving copy treated any MAD below
`abs(median) * 1e-4` as zero; the training copy floored only at exactly zero. For `s8`
and `s13`, whose true MAD is 0.04 against a median of 2388.06, that disagreement meant
the booster was fed 0.0 for two columns it had been trained to see values of about -12
in, and the whole fleet's predictions came out roughly 0.7 cycles optimistic.

The floor now matches training exactly: divide by the MAD, and only substitute 0.0 when
the MAD is zero (or so close that the quotient would overflow). A sensor is treated as
genuinely constant when its MAD says so, not when its magnitude says so.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .errors import ContractError
from .order import SENSORS

# Below this the divisor cannot be trusted to produce a finite, meaningful quotient.
# Matches `eps_mad` in the shipped regime_baselines artifact, so the serving path and
# the artifact that describes it agree on where "zero" begins.
EPS_MAD = 1e-6


def robust_z(value: float, median: float, mad: float, *, eps: float = EPS_MAD) -> float:
    """(value - median) / mad, with 0.0 returned for a sensor that never moves.

    The floor is `eps` alone, deliberately. There is no term proportional to the median:
    that term is what silently zeroed `s8` and `s13`, and with them the entire `fan`
    component, which then read perfectly healthy at end of life.
    """
    if mad <= eps:
        return 0.0
    return (float(value) - float(median)) / float(mad)


def regime_z_scorer(
    stats: dict[str, Any],
    regime: int = 0,
    *,
    subset: str | None = None,
    eps: float = EPS_MAD,
    sensors: Sequence[str] | None = None,
) -> Callable[[dict[str, float]], dict[str, float]]:
    """Build the per-cycle z-score function for a regime.

    Accepts both artifact layouts: the Phase 2 `baselines[regime][sensor]` shape and
    the flatter `regime_<n>` mapping. `sensors` overrides the scored set, which the
    pooled contract needs: it declares 17 base sensors, not the FD001 15.

    Raises ContractError when the requested baseline block is absent. A z-score model
    fed raw features does not fail -- it predicts confidently from the wrong scale --
    so returning None here used to be that failure, silently.
    """
    from .regimes import regime_block

    baseline = regime_block(stats, regime, subset)
    if not baseline:
        raise ContractError(
            f"no baseline block for subset={subset!r} regime={regime}; the model was "
            f"trained on z-scored inputs and cannot be served without them"
        )
    wanted = tuple(sensors) if sensors is not None else SENSORS

    def _score(values: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for sensor in wanted:
            stat = baseline.get(sensor)
            if not stat:
                # A contract sensor the baselines do not describe. It is constant in
                # this subset by construction (that is why it is missing), so its
                # z-score is 0.0 by definition. Skipping it instead left the RAW median
                # in the matrix -- `update()` only adds keys, it never clears them --
                # and the booster then read 1.08 where it was trained to read 0.0.
                out[sensor] = 0.0
                continue
            value = values.get(sensor)
            if value is None:
                continue          # a missing sensor is skipped, not a KeyError
            out[sensor] = robust_z(
                float(value), float(stat["median"]), float(stat.get("mad", 0.0)), eps=eps
            )
        return out

    return _score


__all__ = ["robust_z", "regime_z_scorer", "EPS_MAD"]