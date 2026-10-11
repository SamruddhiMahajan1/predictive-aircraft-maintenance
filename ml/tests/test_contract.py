"""The feature contract itself: shape, arithmetic, and the two things that broke.

These run with no artifact, no model and no database -- the contract is pure standard
library, which is the property that lets training and serving share it.
"""
from __future__ import annotations

import pytest

from rul.contract import (
    FEATURE_ORDER,
    MAX_WINDOW,
    MIN_WINDOW,
    SENSORS,
    ContractError,
    build_matrix,
    contract_sensors,
    contract_widths,
)

S6_MEDIAN = 21.61


def row(cycle: int, **overrides):
    sensors = {
        "s2": 642.7, "s3": 1590.5, "s4": 1400.0 + cycle, "s6": 21.6,
        "s7": 1525.0, "s8": 2538.0, "s9": 2455.0, "s11": 521.9,
        "s12": 1.88, "s13": 2538.0, "s14": 11.72, "s15": 522.2,
        "s17": 641.2, "s20": 542.7, "s21": 2388.0,
    }
    sensors.update(overrides.pop("sensors", {}))
    return {
        "cycle": cycle,
        "settings": {"setting_1": 0.0, "setting_2": 0.0, "setting_3": 0.0},
        "sensors": sensors,
        **overrides,
    }


# ── the contract ───────────────────────────────────────────────────────────────
def test_contract_is_twenty_nine_features():
    assert len(FEATURE_ORDER) == 29
    assert len(FEATURE_ORDER) == len(set(FEATURE_ORDER)), "duplicate column name"


def test_contract_excludes_cycle():
    """cycle correlates with RUL only because the test set is truncated early."""
    assert "cycle" not in FEATURE_ORDER
    assert not any(c.startswith("cycle") for c in FEATURE_ORDER)


def test_contract_starts_with_settings_then_sensors():
    assert FEATURE_ORDER[:2] == ("op1", "op2")
    assert list(FEATURE_ORDER[2:17]) == list(SENSORS)
    assert len(SENSORS) == 15 and "s6" in SENSORS


def test_rolling_columns_come_last_and_in_a_stable_order():
    rolling = [c for c in FEATURE_ORDER if "_roll" in c]
    assert len(rolling) == 12
    assert FEATURE_ORDER[-12:] == tuple(rolling)


def test_every_rolling_column_declares_its_own_width():
    assert contract_widths(FEATURE_ORDER) == {n: 5 for n in FEATURE_ORDER if "_roll" in n}


# ── matrix construction ────────────────────────────────────────────────────────
def test_matrix_shape_matches_the_contract():
    matrix, _ = build_matrix([row(c) for c in range(1, 31)], s6_median=S6_MEDIAN)
    assert len(matrix) == 30
    assert all(len(r) == len(FEATURE_ORDER) for r in matrix)


def test_matrix_columns_follow_the_contract_order():
    matrix, _ = build_matrix([row(c) for c in range(1, 31)], s6_median=S6_MEDIAN)
    s4_index = FEATURE_ORDER.index("s4")
    roll_index = FEATURE_ORDER.index("s4_rollmean5")
    assert matrix[-1][s4_index] == pytest.approx(row(30)["sensors"]["s4"])
    assert matrix[-1][roll_index] == pytest.approx(
        sum(row(c)["sensors"]["s4"] for c in range(26, 31)) / 5
    )


def test_rolling_std_is_zero_at_the_first_cycle():
    """ddof=0 during training, so the first cycle must have std 0 and not NaN."""
    rows = [row(c, sensors={"s9": 2455.0 + 3 * c}) for c in range(1, 7)]
    matrix, _ = build_matrix(rows, s6_median=S6_MEDIAN)
    idx = FEATURE_ORDER.index("s9_rollstd5")
    assert matrix[0][idx] == 0.0            # single sample -> variance 0
    assert matrix[-1][idx] > 0.0
    # ddof=0 over the trailing 5 values: deviations -6,-3,0,3,6 -> var 18
    assert matrix[-1][idx] == pytest.approx(18.0 ** 0.5, rel=1e-6)


def test_absolute_cycles_do_not_reach_the_matrix():
    rows = [row(i) for i in range(1, 7)]
    with_cycles, _ = build_matrix(
        rows, s6_median=S6_MEDIAN, absolute_cycles=[195, 196, 197, 198, 199, 200],
    )
    without, _ = build_matrix(rows, s6_median=S6_MEDIAN)
    assert with_cycles == without


def test_window_is_truncated_to_thirty():
    matrix, _ = build_matrix([row(c) for c in range(1, 51)], s6_median=S6_MEDIAN)
    assert len(matrix) == MAX_WINDOW


@pytest.mark.parametrize("size", [0, 1, MIN_WINDOW - 1])
def test_short_window_is_rejected(size):
    with pytest.raises(ContractError):
        build_matrix([row(c) for c in range(1, size + 1)], s6_median=S6_MEDIAN)


# ── imputation ─────────────────────────────────────────────────────────────────
def test_imputation_names_each_filled_sensor():
    rows = [row(c) for c in range(1, 7)]
    for r in rows:
        r["sensors"].pop("s6")
    _, imputed = build_matrix(rows, s6_median=S6_MEDIAN)
    assert imputed == {"s6"}


def test_a_sensor_absent_from_telemetry_is_filled_not_dropped():
    """Dropping it would shift every later column left by one -- silently."""
    order = list(FEATURE_ORDER) + ["s10"]
    window = [row(c) for c in range(1, 31)]
    matrix, imputed = build_matrix(window, s6_median=S6_MEDIAN, feature_order=order,
                                   missing_sensor_values={"s10": 1.08})
    assert "s10" in imputed
    assert len(matrix[0]) == len(order) == 30
    assert [r[-1] for r in matrix] == [1.08] * 30


# ── multi-subset contracts ─────────────────────────────────────────────────────
def test_contract_sensors_are_derived_from_the_feature_order():
    order = list(FEATURE_ORDER) + ["regime_global", "s10", "s16"]
    found = contract_sensors(order)
    assert len(found) == 17
    assert "s10" in found and "s16" in found
    assert not any("_roll" in s for s in found)
    assert not any(s in found for s in ("op1", "op2", "regime_global"))


def test_contract_sensors_matches_the_fd001_contract():
    assert contract_sensors(FEATURE_ORDER) == SENSORS


def test_pooled_contract_adds_the_regime_column():
    order = list(FEATURE_ORDER) + ["regime_global"]
    matrix, _ = build_matrix([row(c) for c in range(1, 31)], s6_median=S6_MEDIAN,
                             feature_order=order, regime_global=7)
    assert len(matrix[0]) == 30
    assert [r[-1] for r in matrix] == [7.0] * 30


def test_the_29_feature_contract_ignores_the_regime_column():
    matrix, _ = build_matrix([row(c) for c in range(1, 31)], s6_median=S6_MEDIAN,
                             regime_global=7)
    assert len(matrix[0]) == 29


# ── the contract must not know the backend exists ──────────────────────────────
def test_the_contract_imports_no_third_party_and_no_backend_module():
    """`rul.contract` is pure stdlib; that is what makes it shareable.

    A stray `import numpy` here would make the backend's import of the contract depend
    on the ML stack being installed, and an `import app...` would invert the layering
    this package exists to establish.

    Relative imports (`from .errors import ...`) are the package importing itself and
    are fine. What is checked is every module the contract names that lives outside it.
    """
    import ast
    import pathlib
    import sys

    import rul.contract as contract

    stdlib = set(sys.stdlib_module_names)
    root = pathlib.Path(contract.__file__).parent
    seen = 0
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                external = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                # level > 0 means relative: the package importing itself.
                external = [] if node.level else [node.module or ""]
            else:
                continue
            for name in external:
                if not name:
                    continue
                seen += 1
                root_name = name.split(".")[0]
                assert root_name == "rul" or root_name in stdlib, (
                    f"{path.name} imports {name!r}; rul.contract must be pure stdlib "
                    f"(the backend imports it at request time, and an ML-only "
                    f"dependency here would make serving depend on the training stack)"
                )
                assert root_name != "app", (
                    f"{path.name} imports {name!r}; the contract must not depend on the "
                    f"backend -- the dependency runs backend -> ml, never back"
                )
    assert seen, "no imports found -- the guard is not looking at anything"