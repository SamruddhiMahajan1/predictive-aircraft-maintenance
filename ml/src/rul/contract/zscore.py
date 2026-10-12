"""The one robust z-score rule, in one place.

There used to be two of these -- one in the training notebook, one in the serving code --
and they disagreed by a single constant. The serving copy treated any MAD below
`abs(median) * 1e-4` as zero; the training copy floored the divisor at `max(mad, 1e-6)`.
For `s8` and `s13`, whose true MAD is 0.04 against a median of 2388.06, that disagreement
meant the booster was fed 0.0 for two columns it had been trained to see values of about
-12 in, and the whole fleet's predictions came out roughly 0.7 cycles optimistic.

The rule matches training exactly: divide by `max(mad, eps)`. The floor is absolute
(`eps` alone, never proportional to the median) AND it floors the divisor rather than
substituting 0.0. That second half matters: the shipped booster's own splits prove
training saw divisor-floored magnitudes -- `s10` splits at 0/30000, `s16` at 10000,
`s6` at -70000..-10000, exactly `(v - median)/1e-6` for deviations of 0.03/0.01/0.07
on sensors whose healthy MAD is 0.0. Substituting 0.0 for a zero MAD (an earlier
revision of this function did) re-breaks FD002/FD003/FD004, where s10/s16 genuinely
vary across engine life while their healthy-window MAD is 0.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .errors import ContractError
from .order import POOLED_SENSORS

# Below this the divisor cannot be trusted to produce a finite, meaningful quotient.
# Matches `eps_mad` in the shipped regime_baselines artifact, so the serving path and
# the artifact that describes it agree on where "zero" begins.
EPS_MAD = 1e-6


def robust_z(value: float, median: float, mad: float, *, eps: float = EPS_MAD) -> float:
    """(value - median) / max(mad, eps): training's rule, verbatim.

    The floor is `eps` alone, deliberately. There is no term proportional to the
    median: that term is what silently zeroed `s8` and `s13` (MAD 0.04 read as
    "constant"), and with them the entire `fan` component, which then read perfectly
    healthy at end of life.

    And the floor applies to the divisor, not the result: when the MAD is genuinely
    0 (s6/s10/s16 healthy windows read bitwise-constant), training divided by `eps`
    and the booster learned those magnitudes (s10 splits at 30000, s6 at -70000).
    Returning 0.0 there would feed "perfectly healthy" for a sensor training saw at
    ±30000 -- the same bug class as C2, on the multi-regime subsets.
    """
    return (float(value) - float(median)) / max(float(mad), eps)


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

    The default sensor set is the pooled 17 (SENSORS + s10/s16): a subset whose block
    omits a sensor scores it 0.0, which is exactly right for a sensor that is constant
    there (FD001's s10/s16) and never reached for sensors the block describes.
    """
    from .regimes import regime_block

    baseline = regime_block(stats, regime, subset)
    if not baseline:
        raise ContractError(
            f"no baseline block for subset={subset!r} regime={regime}; the model was "
            f"trained on z-scored inputs and cannot be served without them"
        )
    wanted = tuple(sensors) if sensors is not None else POOLED_SENSORS

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