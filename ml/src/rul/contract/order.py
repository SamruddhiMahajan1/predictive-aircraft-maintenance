"""Column order, sensor lists and window geometry. The shape of a feature matrix.

Pure standard library, no data, no model: these are the names and the arithmetic every
other module in this package agrees on.

`cycle` is deliberately NOT an input. It correlates with RUL only because the official
C-MAPSS test set is truncated early, so feeding it produces a model that scores well and
fails on real data. It is still tracked per aircraft, for the fallback and for provenance.
"""

from __future__ import annotations

from collections.abc import Sequence

SPEC_SENSORS = ("s2", "s3", "s4", "s7", "s8", "s9", "s11", "s12",
                "s13", "s14", "s15", "s17", "s20", "s21")
SENSORS = SPEC_SENSORS[:3] + ("s6",) + SPEC_SENSORS[3:]   # 15, s6 included
ROLLING_SENSORS = ("s11", "s4", "s9", "s12", "s14", "s7")
ROLLING_WINDOW = 5
# Used when a derived column name carries no readable width (defensive; every column this
# package emits ends in one).
DEFAULT_ROLLING_WINDOW = ROLLING_WINDOW
ROLLING_SUFFIXES = ("rollmean", "rollstd")
SETTINGS_COLUMNS = ("op1", "op2")

# The extra column a pooled multi-subset contract adds on top of the 29. Absent from the
# FD001 contracts, present (n_features=30) from any candidate naming more than one
# subset -- so it is read from the contract rather than hard-coded into FEATURE_ORDER.
REGIME_COLUMN = "regime_global"

MIN_WINDOW = 5
MAX_WINDOW = 30

# Rolling standard deviation is population variance (ddof=0), not sample. The booster
# learned thresholds at that scale; ddof=1 shifts every `_rollstd` column by a factor
# that depends on the window fill, which is silent in a positional matrix.
ROLLING_DDOF = 0

# Column order is a CONTRACT, not an implementation detail: XGBoost consumes a
# positional matrix, so a reordered list yields plausible-looking wrong predictions.
FEATURE_ORDER: tuple[str, ...] = tuple(
    list(SETTINGS_COLUMNS)
    + list(SENSORS)
    + [
        f"{s}_{suffix}{ROLLING_WINDOW}"
        for s in ROLLING_SENSORS
        for suffix in ROLLING_SUFFIXES
    ]
)


def contract_sensors(feature_order: Sequence[str]) -> tuple[str, ...]:
    """Base sensors a contract needs, derived from its own feature_order.

    Not read from the hardcoded SENSORS tuple. A pooled multi-subset contract declares
    a different sensor set per subset and appends sensors that are constant in FD001 but
    live in FD002/FD004 (`s10`, `s16`), so the 29-column FD001 list is not a superset of
    it -- the pooled contract is 32 columns wide and building the FD001 29 produced a
    positional matrix that was silently misaligned, not merely short.
    """
    derived = set()
    for name in feature_order:
        if "_roll" in name:
            derived.add(name.split("_roll", 1)[0])
    skip = set(SETTINGS_COLUMNS) | {REGIME_COLUMN}
    # `_roll` columns are excluded by name, not by membership of their base sensor:
    # `s11_rollmean5` is not itself a key of `derived` (that holds `s11`), so testing
    # against `derived` let every rolling column through as if it were a raw sensor.
    return tuple(
        n for n in feature_order
        if n not in skip and "_roll" not in n
    )


__all__ = [
    "SPEC_SENSORS",
    "SENSORS",
    "ROLLING_SENSORS",
    "ROLLING_WINDOW",
    "DEFAULT_ROLLING_WINDOW",
    "ROLLING_SUFFIXES",
    "ROLLING_DDOF",
    "SETTINGS_COLUMNS",
    "REGIME_COLUMN",
    "MIN_WINDOW",
    "MAX_WINDOW",
    "FEATURE_ORDER",
    "contract_sensors",
]