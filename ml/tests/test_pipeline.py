"""Pipeline skeleton tests (docs/16 §10.7). Fast, no data, no sklearn."""

from pathlib import Path


def test_configs_load_and_reject_unknown():
    from rul.config import load_config

    for name in ("base", "fd001", "fd001_fd003", "all"):
        cfg = load_config(name)
        assert cfg.datasets
        assert cfg.model.max_depth == 6
    import pytest, tomllib

    # Unknown keys fail hard.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write('name="x"\ndatasets=["FD001"]\n[model]\nmax_depth=6\nearly_stopping_rond=50\n')
        p = f.name
    with pytest.raises(ValueError, match="unknown keys"):
        load_config(p)


def test_per_row_regime_single_regime_matches_single():
    from rul.contract import build_matrix, build_matrix_per_row_regime

    window = [
        {"cycle": i + 1, "settings": {"setting_1": 0.0, "setting_2": 0.0, "setting_3": 100.0},
         "sensors": {s: 10.0 for s in ("s2", "s3", "s4", "s6", "s7", "s8", "s9", "s11", "s12", "s13", "s14", "s15", "s17", "s20", "s21")}}
        for i in range(6)
    ]
    stats = {"baselines": {"FD001": {"0": {s: {"median": 10.0, "mad": 1.0} for s in ("s2", "s3", "s4", "s6", "s7", "s8", "s9", "s11", "s12", "s13", "s14", "s15", "s17", "s20", "s21")}}}}
    from rul.contract import regime_z_scorer

    scorer = regime_z_scorer(stats, 0, subset="FD001")
    m1, _ = build_matrix(window, s6_median=10.0, sensors_to_z=scorer)
    m2, _, regimes = build_matrix_per_row_regime(
        window, s6_median=10.0, stats=stats, subset="FD001", centroids=[[0.0, 0.0, 100.0]]
    )
    assert regimes == [0] * len(window)
    assert len(m1) == len(m2) and len(m1[0]) == len(m2[0])


def test_registry_promote_gates():
    import json, tempfile
    from rul.registry.manifest import write_run
    from rul.registry.promote import can_promote
    from rul.config import load_config

    cfg = load_config("fd001")
    with tempfile.TemporaryDirectory() as td:
        rd = write_run(td, config=cfg.resolved_dict(),
                       metrics={"cv_rmse_mean": 99.0, "gate_failures": ["cv_rmse 99 > 21"], "data_sha256": {}},
                       artifacts={}, seed=42)
        ok, reasons = can_promote(rd)
        assert not ok  # gates failed + no data manifest
        assert any("gates" in r or "manifest" in r for r in reasons)
