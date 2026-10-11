"""The MAD rule, which is the root cause of the worst defect in this repository.

`s8` and `s13` have a genuine MAD of 0.04 against a median of 2388.06. A floor of
`abs(median) * 1e-4` computes to 0.2388 and treats both as constant, so the booster was
fed 0.0 for two columns it had been trained to see values of about -12 in. Predictions
came out ~0.7 cycles optimistic, and because `domain/rules.py` maps the `fan` component
to exactly those two sensors, `fan` was pinned to perfect health forever and could never
select a spare or raise an alert.

The numbers here are the shipped artifact's own values, so this test fails if someone
reintroduces a magnitude-proportional floor.
"""
from __future__ import annotations

import pytest

from rul.contract import EPS_MAD, SENSORS, robust_z

# Verbatim from backend/data/ml/all/regime_baselines_all.json, baselines.FD001.0.
FD001_S8 = {"median": 2388.06, "mad": 0.04}
FD001_S6 = {"median": 21.61, "mad": 0.0}


def test_a_small_mad_is_still_divided_by_not_floored():
    """s8 at +0.04 from its median is z = +1.0, not z = 0.0."""
    assert robust_z(2388.10, FD001_S8["median"], FD001_S8["mad"]) == pytest.approx(1.0)


def test_a_large_relative_deviation_is_reported_at_full_magnitude():
    """The end-of-life reading training saw: ~-12 sigma, not a clipped 0.0."""
    z = robust_z(2386.62, FD001_S8["median"], FD001_S8["mad"])
    assert z == pytest.approx(-36.0, rel=1e-3)
    assert abs(z) > 10.0, "the defect presented as a pinned zero, not a small value"


def test_a_genuinely_zero_mad_still_floors():
    """s6 is constant in FD001; dividing by zero must not be attempted."""
    assert robust_z(21.61, FD001_S6["median"], FD001_S6["mad"]) == 0.0
    assert robust_z(999.0, FD001_S6["median"], FD001_S6["mad"]) == 0.0


def test_the_floor_is_absolute_never_proportional_to_the_median():
    """The guard against the floor being reintroduced in any magnitude-aware form.

    A MAD of 1e-5 against a median of 1e6 is 1e-11 of the median. The removed rule
    called that constant and scored it 0.0. It is not constant -- its healthy readings
    genuinely differ -- and the correct answer is the full quotient. Only a MAD at or
    below the absolute `eps` may be floored.
    """
    assert robust_z(1_000_000.0, 1e6, 1e-9) == 0.0          # below eps: floored
    z = robust_z(1_000_001.0, 1e6, 1e-5)                    # above eps: divided
    # The quotient is ~1e5, which a float cannot hold to full precision after the
    # subtraction, so compare against the sign and order of magnitude rather than an
    # exact value. What matters is that it is not 0.0.
    assert z > 1e4
    assert z != 0.0


def test_eps_matches_the_artifact():
    """The artifact carries `eps_mad`; the serving path must use the same constant."""
    import json
    import pathlib

    # ml/tests/test_zscore.py -> repo root is parents[2]
    path = pathlib.Path(__file__).resolve().parents[2] / "backend/data/ml/all/regime_baselines_all.json"
    if not path.exists():
        pytest.skip("regime_baselines artifact not staged")
    assert json.loads(path.read_text())["eps_mad"] == EPS_MAD


def test_no_magnitude_proportional_floor_exists_in_the_contract():
    """Structural guard: the constant is gone from the whole package, not just unused.

    Parses the source rather than grepping it, and looks at code only -- a docstring
    that explains what the removed floor was is documentation worth keeping. A
    reintroduced floor that happens to pass today's fixtures is exactly how this defect
    survived a fully green suite the first time, so the check has to see an actual
    expression rather than a substring anywhere in the file.
    """
    import ast
    import pathlib

    import rul.contract as contract

    root = pathlib.Path(contract.__file__).parent
    checked = 0
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, float):
                continue
            checked += 1
            assert node.value != 1e-4, (
                f"{path.name}:{node.lineno} reintroduces the 1e-4 relative MAD floor "
                f"as a literal"
            )
    assert checked, "no float constants found -- the guard is not looking at anything"


def test_s8_and_s13_are_both_affected_sensors():
    """Both `fan` inputs, so a fix that only repairs one leaves the component broken."""
    assert "s8" in SENSORS and "s13" in SENSORS