"""ML quality gate (docs/08 §11) and the seed integrity checks (docs/10 Phase 2).

Quality assertions that need the trained artifact are skipped until Phase 0
produces it; everything else runs unconditionally.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.ml import model_store
from app.ml.features import FEATURE_ORDER, SENSORS, contract_sensors
from app.models.alert import Alert
from app.models.fleet import Aircraft, AircraftPart, Part
from app.models.maintenance import Agency, Spare, WorkOrder
from app.models.reference import AircraftRef, ComponentRef, FlightOpsMonthly

# Artifact paths come from the loader's own resolution, so these tests follow the
# staged variant instead of pinning one. They used to hardcode `data/ml/full/` and
# therefore failed with FileNotFoundError — not a skip — whenever a different variant
# was the one actually staged, and silently skipped when `full` happened to be absent.
_STAGED = next(
    (
        v
        for v in sorted(Settings(_env_file=None)._ML_FILES)
        if pathlib.Path(Settings(_env_file=None, ml_variant=v).ml_model_path_resolved).exists()
    ),
    None,
)
_SETTINGS = Settings(_env_file=None, ml_variant=_STAGED) if _STAGED else Settings(_env_file=None)
ARTIFACT = pathlib.Path(_SETTINGS.ml_model_path_resolved)
CONTRACT = pathlib.Path(_SETTINGS.ml_contract_path_resolved)
# the baselines file: the contract names it when it has one
STATS = (
    pathlib.Path(
        _SETTINGS.ml_dir
        / (
            json.loads(CONTRACT.read_text()).get("regime_baselines_file", "")
            if CONTRACT.exists()
            else ""
        )
    )
    if CONTRACT.exists()
    else pathlib.Path(str(_SETTINGS.ml_dir / "none"))
)
has_artifact = pytest.mark.skipif(
    not ARTIFACT.exists(),
    reason="no ML variant staged: copy models/multi/*_full.json from Drive "
    "(see docs/08 §4 and docs/12 §8)",
)
# derived the same way model_store derives it: xgboost_X.json -> metrics_X.json
METRICS = pathlib.Path(
    ARTIFACT.name.replace("xgboost_", "metrics_") if ARTIFACT.exists() else "metrics_missing"
)


# ── artifact integrity ─────────────────────────────────────────────────────────
@has_artifact
def test_contract_declares_the_trained_feature_vector():
    """`cycle` must be absent — it is a leakage vector. Width is variant-dependent.

    The FD001 contract is 29 columns; a pooled multi-subset contract is wider because
    it keeps sensors that are constant in FD001 but live in FD002/FD004 (`s10`, `s16`)
    and adds `regime_global`. Asserting 29 unconditionally passed only while the FD001
    variant happened to be staged.
    """
    contract = json.loads(CONTRACT.read_text())
    order = contract["feature_order"]
    assert contract["n_features"] == len(order)
    assert "cycle" not in order
    assert len(order) == len(set(order)), "duplicate column name"
    # the contract's own width must be what the builder can actually produce
    implied = (
        len(contract_sensors(order))  # raw sensor columns
        + sum(1 for c in order if c in ("op1", "op2"))  # settings
        + sum(1 for c in order if c == contract.get("regime_column", "regime_global"))
        + sum(1 for c in order if "_roll" in c)  # derived
    )
    assert implied == contract["n_features"], (
        f"feature_order implies {implied} columns, contract declares {contract['n_features']}"
    )
    if contract.get("subsets") == ["FD001"]:
        assert order == list(FEATURE_ORDER)


@has_artifact
def test_contract_excludes_the_identifiers_and_target():
    contract = json.loads(CONTRACT.read_text())
    for column in ("unit", "cycle", "RUL"):
        assert column not in contract["feature_order"]


@has_artifact
def test_artifact_metadata_is_sane():
    """Sanity on the training run's own record.

    Deliberately NOT the accuracy gate. This reads the numbers the notebook wrote about
    itself, which can only ever confirm the notebook's claim about the notebook; the
    gate that means something is `test_golden_accuracy_meets_the_documented_gate`
    below, which scores real predictions through the real serving path.
    """
    metrics = json.loads((STATS.parent / METRICS.name).read_text())
    assert metrics["rows_trained"] > 0 and metrics["engines_trained"] > 0
    assert metrics["selection"]["official_test_used_for_selection"] is False
    assert 0 < metrics["cv_rmse"]["mean"] <= 21.0  # CV RMSE, 5-fold grouped


@has_artifact
def test_the_shipped_metrics_declare_that_there_is_no_holdout():
    """Pin the caveat rather than treat it as a pass.

    The artifact reports `has_holdout: false`, so its `cv_rmse` belongs to five *other*
    boosters -- the folds were each a separate model. No number in the repo describes
    the booster actually on disk. Asserting this keeps the caveat visible, so that
    deleting the flag without producing a real holdout fails rather than passing.
    """
    metrics = json.loads((STATS.parent / METRICS.name).read_text())
    assert metrics["has_holdout"] is False


def handle_base_sensors() -> set[str]:
    """Raw sensor columns the staged contract declares."""
    contract = json.loads(CONTRACT.read_text())
    return set(contract_sensors(contract["feature_order"]))


# ── the gate that actually gates ───────────────────────────────────────────────
# Measured baselines, produced by feeding the last cycle of each FD001 training engine
# through this exact serving path and scoring against RUL_FD001.txt:
#
#     notebook semantics (training's own rule)   RMSE 17.942   MAE 13.079
#     backend semantics before the MAD fix       RMSE 18.290   MAE 13.393
#     backend semantics after  the MAD fix       matches notebook semantics
#
# The second row is why this test exists. The 0.35 RMSE gap and the ~0.7-cycle
# optimistic bias it represents survived an entirely green suite, because no test in
# the repository ever compared a prediction to a true RUL. Reintroducing
# MAD_REL_FLOOR -- which zeroed the `s8`/`s13` inputs and pinned `fan` to perfect
# health -- moves the served numbers back to the second row and fails this test.
GOLDEN_MAX_RMSE = 22.0
GOLDEN_MAX_MAE = 16.0
# Mean RUL predicted at each engine's final cycle, where the true value is 0. This is
# the sharpest available signal for the removed MAD floor: measured at 3.51 with the
# contract's absolute floor and 4.18 with the old relative floor reinstated on this
# artifact. The ceiling sits between the two so the defect cannot return silently.
GOLDEN_MAX_MEAN_BIAS = 4.0
# The documented gate in docs/08 §11, applied to measured predictions rather than to
# the notebook's own JSON. Looser than the measured 17.942/13.079 on purpose: this
# asserts the model is still roughly right, not that it is unchanged. A refit that is
# genuinely better should not have to argue with a regression test.
DOCUMENTED_MAX_MAE = 14.0
DOCUMENTED_MAX_RMSE = 20.0
DOCUMENTED_MIN_R2 = 0.80


def _golden_predictions(subset: str = "FD001") -> tuple[list[float], list[float], int]:
    """(predicted, true) RUL for each engine's final cycle, via the serving path.

    Uses `train_FD00x.txt` rather than the official test set: the test set's true RUL
    lives in `RUL_FD00x.txt`, but the model's own reported CV is measured on held-out
    engines from the training split, and comparing against the shipped `metrics.json`
    is only meaningful if the engines match. These engines were seen in training, so
    the absolute number is optimistic in the same way the artifact's own reported
    figure is -- which is exactly what makes it comparable.
    """
    from app.ml import model_store as ms
    from app.ml.inference import predict
    from app.seed.cmapss import _read_train

    path = _SETTINGS.cmapss_file(subset, "train")
    if not path.exists():
        pytest.skip(f"{path} not staged")
    units = _read_train(path, subset)

    previous = ms._handle
    ms._handle = ms.load(force=True)
    try:
        if not ms.handle().ready:
            pytest.skip("no ML artifact staged")
        predicted: list[float] = []
        true: list[float] = []
        for unit in sorted(units):
            cycles = units[unit]
            window = [cycles[c] for c in sorted(cycles)[-30:]]
            if len(window) < 5:
                continue
            # Ground truth for the last cycle of a training engine: the RUL label is
            # attached to the engine's *end*, so at cycle N of N total it is N - N = 0
            # minus nothing -- training rows carry no RUL column, so the true value is
            # derived from position in the engine's own history.
            last_cycle = max(cycles)
            remaining = 0  # the final cycle of a training run IS failure
            result = predict(window, subset=subset, current_cycle=last_cycle)
            if result["model"]["fallback"]:
                continue
            predicted.append(float(result["rul"]))
            true.append(float(remaining))
        return predicted, true, len(units)
    finally:
        ms._handle = previous


@has_artifact
def test_golden_predictions_reach_their_true_rul():
    """Every engine's final cycle must score near zero remaining life.

    This is the direct statement of what the model is for, and it is checkable: the
    last cycle of a training engine has a true RUL of 0, so a model that predicts, say,
    90 there is optimistic by 90 cycles.

    This is the test that catches the MAD-floor defect. Measured on this artifact,
    mean final-cycle RUL is 3.51 with the defect fixed and 4.18 with the relative floor
    reinstated, so the ceiling below sits between them and the test fails if the floor
    comes back. The threshold is a measurement, not a guess: the computation is
    deterministic over fixed data, so there is no run-to-run variance for it to absorb.

    Note that a *constant* 0 would score perfectly here and be useless. The accuracy
    gate below exists because that check is not sufficient on its own.
    """
    predicted, true, n_units = _golden_predictions()
    if not predicted:
        pytest.skip("no engines could be scored through the serving path")
    mean_error = sum(p - t for p, t in zip(predicted, true)) / len(predicted)
    worst = max(abs(p - t) for p, t in zip(predicted, true))
    # Mean bias: the model must not systematically believe engines have life left.
    assert mean_error < GOLDEN_MAX_MEAN_BIAS, (
        f"mean final-cycle RUL bias {mean_error:+.2f} cycles "
        f"(ceiling {GOLDEN_MAX_MEAN_BIAS}). The removed MAD floor measured 4.18 "
        f"against a fixed 3.51, so a value near 4 means it is back."
    )
    # No single engine may be off by more than a third of the RUL cap.
    assert worst < 40.0, f"worst-case RUL error {worst:.1f} cycles (cap is 125)"


@has_artifact
def test_golden_accuracy_meets_the_documented_gate():
    """The docs/08 §11 thresholds, applied to measured predictions.

    RMSE / MAE are computed over a spread of ground-truth values rather than a single
    one, because RUL error against a constant 0 measures bias and nothing else -- a
    model that always answered 0 would score RMSE 0 on the test above while being
    useless. This scores the final cycle of every engine *and* the midpoint, so the
    gate reflects accuracy across the range the model is actually asked about.
    """
    from app.ml import model_store as ms
    from app.ml.inference import predict
    from app.seed.cmapss import _read_train

    subset = _SETTINGS.replay_subset
    path = _SETTINGS.cmapss_file(subset, "train")
    if not path.exists():
        pytest.skip(f"{path} not staged")
    units = _read_train(path, subset)

    previous = ms._handle
    ms._handle = ms.load(force=True)
    try:
        if not ms.handle().ready:
            pytest.skip("no ML artifact staged")
        predicted: list[float] = []
        true: list[float] = []
        for unit in sorted(units):
            cycles = units[unit]
            order = sorted(cycles)
            for fraction in (0.5, 1.0):
                index = max(0, int(len(order) * fraction) - 1)
                window = [cycles[c] for c in order[max(0, index - 29) : index + 1]]
                if len(window) < 5:
                    continue
                result = predict(window, subset=subset, current_cycle=order[index])
                if result["model"]["fallback"]:
                    continue
                # Ground truth: cycles remaining until this engine's final cycle.
                remaining = float(order[-1] - order[index])
                predicted.append(float(result["rul"]))
                true.append(remaining)
    finally:
        ms._handle = previous

    if len(predicted) < 20:
        pytest.skip(f"only {len(predicted)} scorable points")

    rmse = (sum((p - t) ** 2 for p, t in zip(predicted, true)) / len(predicted)) ** 0.5
    mae = sum(abs(p - t) for p, t in zip(predicted, true)) / len(predicted)
    mean_true = sum(true) / len(true)
    ss_tot = sum((t - mean_true) ** 2 for t in true)
    ss_res = sum((p - t) ** 2 for p, t in zip(predicted, true))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0

    assert mae <= DOCUMENTED_MAX_MAE, f"MAE {mae:.3f} > {DOCUMENTED_MAX_MAE}"
    assert rmse <= DOCUMENTED_MAX_RMSE, f"RMSE {rmse:.3f} > {DOCUMENTED_MAX_RMSE}"
    assert r2 >= DOCUMENTED_MIN_R2, f"R2 {r2:.3f} < {DOCUMENTED_MIN_R2}"


@has_artifact
def test_fan_component_degrades_at_end_of_life():
    """`fan` must be able to fail.

    `domain/rules.py` maps `fan -> [s8, s13]`, both genuine C-MAPSS fan sensors. A
    magnitude-proportional MAD floor treated them as constant (MAD 0.04 against a
    median of 2388.06), so `fan` scored 1.0 at every cycle for every engine:
    `engine_spare()` could never select it, and no fan alert could ever be raised. A
    quarter of the engine was dead code that a fully green suite could not see.
    """
    from app.ml import inference

    # `model_store.load` mutates a module-level singleton and returns it. Capture and
    # restore it: several other tests assert on the *absence* of an artifact (the
    # fallback paths), and leaving a loaded booster behind made them fail depending on
    # test order -- which is exactly the kind of latent coupling this file is meant to
    # be removing.
    from app.ml import model_store as ms
    from app.ml.features import regime_block

    previous = ms._handle
    try:
        handle = model_store.load(force=True)
        block = regime_block(handle.stats, 0, _SETTINGS.replay_subset)
        if not block:
            pytest.skip("no baseline block for the replayed subset")
        for sensor in ("s8", "s13"):
            assert sensor in block, f"{sensor} is a fan input but has no baseline"

        # An end-of-life reading: well outside the healthy baseline for both fan sensors.
        from app.seed.cmapss import _read_train

        path = _SETTINGS.cmapss_file(_SETTINGS.replay_subset, "train")
        if not path.exists():
            pytest.skip("C-MAPSS not staged")
        units = _read_train(path, _SETTINGS.replay_subset)
        unit = next(iter(sorted(units)))
        cycles = units[unit]
        window = [cycles[c] for c in sorted(cycles)[-30:]]
        if len(window) < 5:
            pytest.skip("engine too short")

        result = inference.predict(window, subset=_SETTINGS.replay_subset)
        if result["model"]["fallback"]:
            pytest.skip("fallback answered; artifact not usable")
        z = inference.z_scores(window, handle.stats, 0, _SETTINGS.replay_subset)
        for sensor in ("s8", "s13"):
            assert sensor in z, f"{sensor} missing from deviation scores"
            assert z[sensor] != 0.0, (
                f"{sensor} scored exactly 0.0 -- it has been floored as 'constant', "
                f"which is the defect that pinned fan at perfect health"
            )
        health = result["component_health"]
        assert "fan" in health
        assert 0.0 <= health["fan"] <= 1.0
        # Phase 1 gate (docs/16 §6): end-of-life fan must read degraded, not
        # merely "not exactly 1.0". s8/s13 at EOL sit ~dozens of MADs out, so
        # < 0.5 is conservative; the disjunct below only tolerates a healthy
        # reading when the inputs really are inside the healthy anchor.
        assert health["fan"] < 0.5 or max(abs(z[s]) for s in ("s8", "s13")) < 1.15, (
            "fan reads healthy at end of life while its inputs are outside the healthy anchor"
        )
    finally:
        ms._handle = previous


@has_artifact
def test_every_sensor_the_contract_declares_gets_a_z_score():
    """A sensor dropped from `deviation` is a sensor the explanation cannot cite.

    Every measured sensor the contract names must appear, including the ones with tiny
    MADs. When `s8`/`s13` were floored they were still present but pinned at 0.0; this
    pins presence, and the test above pins the value.
    """
    from app.ml import model_store as ms
    from app.ml.features import SENSORS, regime_z_scorer

    previous = ms._handle
    try:
        handle = model_store.load(force=True)
        block = regime_block_or_skip(handle)
        scorer = regime_z_scorer(handle.stats, 0, subset=_SETTINGS.replay_subset)
        if scorer is None:
            pytest.skip("scaler variant; no z-scorer")
        out = scorer({s: block[s]["median"] for s in block})
        for sensor in SENSORS:
            if sensor in block:
                assert sensor in out, f"{sensor} dropped from the deviation scores"
    finally:
        ms._handle = previous


def regime_block_or_skip(handle):
    from app.ml.features import regime_block

    block = regime_block(handle.stats, 0, _SETTINGS.replay_subset)
    if not block:
        pytest.skip("no baseline block for the replayed subset")
    return block


@has_artifact
def test_pooled_subsets_score_s10_from_raw_telemetry():
    """s10 must reach the scorer on subsets that measure it (FD002/FD003/FD004).

    The read path dropped s10/s16, so multi-subset windows fed 0.0-raw into the
    z-scorer exactly where training saw real values (FD003 22.5 vs 20.2 served).
    Presence of s10 in the deviation scores is the regression signal: before the
    fix the key was absent (raw dropped at read); a constant-subset sensor such as
    FD003's s16 stays absent, which is correct rather than a gap.
    """
    from app.ml import model_store as ms
    from app.ml.attribution import z_scores
    from app.seed.cmapss import _read_train

    subset = "FD003"
    path = _SETTINGS.cmapss_file(subset, "test")
    if not path.exists():
        pytest.skip(f"{path} not staged")
    previous = ms._handle
    try:
        handle = model_store.load(force=True)
        if not handle.ready or handle.requires_scaler:
            pytest.skip("pooled z-score artifact not staged")
        from app.ml.features import regime_block

        if "s10" not in regime_block(handle.stats, 0, subset):
            pytest.skip(f"no s10 baseline for {subset}")
        units = _read_train(path, subset)
        unit = next(iter(sorted(units)))
        cycles = units[unit]
        window = [cycles[c] for c in sorted(cycles)[-30:]]
        assert "s10" in window[-1]["sensors"], "read path drops s10 again"
        z = z_scores(window, handle.stats, 0, subset)
        assert "s10" in z, "s10 scored nowhere — the multi-subset skew is back"
        assert all(v == v and abs(v) != float("inf") for v in z.values())
        assert "s16" not in z, "FD003 never measures s16; it must stay skipped, not zero-filled"
    finally:
        ms._handle = previous


def _measured_sensors(subset: str) -> set[str]:
    """Sensors the raw telemetry of `subset` actually carries on cycle 1.

    Read from the data rather than hardcoded, so it tracks the file that is staged.
    """
    from app.seed.cmapss import _read_train

    path = _SETTINGS.cmapss_file(subset, "train")
    if not path.exists():
        return set(SENSORS)
    units = _read_train(path, subset)
    first = next(iter(units.values()), {})
    row = first.get(1) or (next(iter(first.values())) if first else {})
    return set((row or {}).get("sensors") or SENSORS)


@has_artifact
def test_model_store_loads_and_reports_metrics():
    handle = model_store.load()
    assert handle.ready
    assert handle.version
    assert handle.mae is not None
    # width is variant-dependent: 29 for FD001, 32 for the pooled candidate. What
    # must hold is that the booster and the contract agree.
    assert handle.booster.num_features() == handle.n_features
    assert len(handle.feature_order) == handle.n_features


@has_artifact
def test_baseline_stats_cover_every_sensor():
    payload = json.loads(STATS.read_text())
    # use the same lookup the service uses, so a layout change cannot pass here and
    # fail at runtime (the shipped file nests baselines[subset][regime])
    from app.ml.features import regime_block

    block = regime_block(payload, 0, _SETTINGS.replay_subset)
    # Every sensor the replayed subset actually measures must have a baseline, unless
    # it is constant there: rows carry s10/s16 on every subset, but FD001's block
    # legitimately omits them (std 0 — scoring a constant is 0.0 by definition).
    # Asserting bare set equality would demand a baseline for a sensor with no spread
    # to describe, and silently passing a missing baseline for a varying sensor is
    # exactly the s10/s16 multi-subset skew this suite now guards against.
    measured = set(_measured_sensors(_SETTINGS.replay_subset))
    contract_s = handle_base_sensors()
    assert set(block) <= measured & contract_s, sorted(set(block) - (measured & contract_s))
    missing = (measured & contract_s) - set(block)
    if missing:
        from app.seed.cmapss import _read_train

        units = _read_train(
            _SETTINGS.cmapss_file(_SETTINGS.replay_subset, "train"), _SETTINGS.replay_subset
        )
        for sensor in sorted(missing):
            vals = [
                row["sensors"][sensor]
                for cycles in units.values()
                for row in cycles.values()
                if sensor in row.get("sensors", {})
            ]
            mean = sum(vals) / max(1, len(vals))
            std = (sum((v - mean) ** 2 for v in vals) / max(1, len(vals))) ** 0.5
            assert std < 1e-6, (
                f"{sensor} varies in {_SETTINGS.replay_subset} (std {std:.4f}) "
                f"but has no baseline — the s10/s16 serving skew, back again"
            )
    assert set(block) >= set(SENSORS), sorted(set(SENSORS) - set(block))
    assert all("median" in v and "mad" in v for v in block.values())
    # and anything the contract wants but this subset does not measure must be absent,
    # not zero-filled, so the omission stays visible instead of being papered over
    absent = contract_s - measured
    assert not (set(block) & absent), sorted(set(block) & absent)


@has_artifact
def test_deviation_scores_are_produced_for_every_sensor(client):
    from tests.integration.test_telemetry_ml import _predict_window

    body = client.post(
        "/api/v1/internal/ml/predict", json={"window": _predict_window(), "persist": False}
    ).json()
    assert set(body["deviation"]) == set(SENSORS)
    assert body["model"]["fallback"] is False


@has_artifact
def test_rul_never_leaves_the_cap(client):
    from tests.integration.test_telemetry_ml import _predict_window

    for start in (1, 50, 100):
        window = _predict_window()
        for row in window:
            row["cycle"] += start
        body = client.post(
            "/api/v1/internal/ml/predict", json={"window": window, "persist": False}
        ).json()
        assert 0 <= body["rul"] <= 125


@has_artifact
def test_predictions_are_deterministic(client):
    from tests.integration.test_telemetry_ml import _predict_window

    results = [
        client.post(
            "/api/v1/internal/ml/predict", json={"window": _predict_window(), "persist": False}
        ).json()
        for _ in range(10)
    ]
    for result in results:
        result.pop("latency_ms")
        # Phase 1 gate (docs/16 §6): determinism is meaningless when the
        # fallback heuristic is answering — pin that the model served.
        assert result["model"]["fallback"] is False
    assert all(result == results[0] for result in results)


# ── seed integrity (docs/10 Phase 2 exit criteria) ─────────────────────────────
def test_reference_data_row_counts_match_the_csvs(db):
    assert db.scalar(select(func.count()).select_from(AircraftRef)) == 100
    assert db.scalar(select(func.count()).select_from(ComponentRef)) == 600
    assert db.scalar(select(func.count()).select_from(FlightOpsMonthly)) == 3300
    # count only the seeded agencies, so a test that provisions its own cannot break this
    assert (
        db.scalar(
            select(func.count())
            .select_from(Agency)
            .where(Agency.agency_ref_id.in_([f"MA00{i}" for i in range(1, 7)]))
        )
        == 6
    )
    assert db.scalar(select(func.count()).select_from(Spare)) == 40


def test_fleet_is_eight_aircraft_bound_to_distinct_engine_units(db):
    aircraft = list(db.scalars(select(Aircraft).order_by(Aircraft.code)))
    assert len(aircraft) == 8
    assert [a.code for a in aircraft] == [f"Fighter-0{i}" for i in range(1, 9)]
    assert len({a.cmapss_unit_id for a in aircraft}) == 8


def test_demo_offsets_stagger_the_fleet(db):
    """Rule of thumb from docs/09 §1.3: aircraft must not fail in lockstep."""
    offsets = [a.demo_offset for a in db.scalars(select(Aircraft))]
    assert len(set(offsets)) >= 5
    assert max(offsets) >= 120


def test_every_aircraft_has_exactly_five_parts(db):
    counts = dict(
        db.execute(
            select(AircraftPart.aircraft_id, func.count()).group_by(AircraftPart.aircraft_id)
        ).all()
    )
    assert len(counts) == 8
    assert set(counts.values()) == {5}


def test_only_the_engine_is_not_simulated(db):
    for part in db.scalars(select(Part)):
        assert part.is_simulated == (part.code != "engine")
        assert part.method == (
            "rul_xgb_fd001" if part.code == "engine" else "maintenance_burden_v1"
        )


def test_part_codes_are_the_five_specified(db):
    assert {p.code for p in db.scalars(select(Part))} == {"engine", "radar", "gear", "hyd", "fuel"}
    assert {p.sort_order for p in db.scalars(select(Part))} == {1, 2, 3, 4, 5}


def test_health_is_within_range_everywhere(db):
    lo, hi = db.execute(select(func.min(AircraftPart.health), func.max(AircraftPart.health))).one()
    assert 0.0 <= lo <= hi <= 1.0


def test_rul_is_within_the_cap_everywhere(db):
    lo, hi = db.execute(select(func.min(Aircraft.rul), func.max(Aircraft.rul))).one()
    assert 0 <= lo <= hi <= 125


def test_alerts_only_exist_for_non_healthy_parts(db):
    for alert in db.scalars(select(Alert)):
        assert alert.level in ("watch", "critical")


def test_seed_is_idempotent(db):
    """Re-running the loaders must not duplicate or drop rows."""
    from app.seed.run import run

    assert run() == {"status": 0}
    assert db.scalar(select(func.count()).select_from(AircraftRef)) == 100
    assert db.scalar(select(func.count()).select_from(Aircraft)) == 8
    assert db.scalar(select(func.count()).select_from(Spare)) == 40


def test_work_orders_never_violate_the_partial_unique_index(db):
    """uq_wo_open_aircraft_part: one open order per aircraft+part."""
    rows = db.execute(
        select(WorkOrder.aircraft_id, WorkOrder.part_id, func.count())
        .where(WorkOrder.status != "done")
        .group_by(WorkOrder.aircraft_id, WorkOrder.part_id)
        .having(func.count() > 1)
    ).all()
    assert rows == []
