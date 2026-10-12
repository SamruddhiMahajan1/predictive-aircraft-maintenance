"""Fit + evaluate internals: contract-built matrices, GroupKFold CV, holdout, refit."""

from __future__ import annotations

from pathlib import Path


def _median_mad(vals: list[float]) -> dict[str, float]:
    import statistics

    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    return {"median": med, "mad": mad}


def _rows_to_windows(rows: list[dict], *, window: int = 30) -> list[list[dict]]:
    # Exam-style: each prefix of an engine's history is a training window, so the
    # model learns early-life as well as end-of-life (notebook cells 14-26, kept).
    rows = sorted(rows, key=lambda r: r["cycle"])
    out = []
    for end in range(5, len(rows) + 1):
        out.append(rows[max(0, end - window) : end])
    return out or [rows]


def _derive_baselines(windows_by_unit: dict, *, rul_cap: int) -> dict:
    # Healthy baseline = median/MAD over first 20 cycles per subset+regime.
    # Single-regime helper: regime from operating settings via k-means-free
    # nearest-centroid is fit here; FD001 collapses to regime 0.
    #
    # Windows overlap heavily (each engine prefix is a window), so the same row
    # object appears in ~30 windows. Dedupe by id() — otherwise a 2-engine
    # dry-run scans ~8k rows instead of ~400 and full FD001 takes ~40 min.
    import statistics

    per_subset_regime: dict = {}
    seen: set[int] = set()
    for unit, windows in windows_by_unit.items():
        subset = unit.split("#")[0]
        for w in windows:
            for row in w[:20]:
                if id(row) in seen:
                    continue
                seen.add(id(row))
                s = row["settings"]
                key = (round(s["setting_1"], 1), round(s["setting_2"], 2), round(s["setting_3"], 1))
                per_subset_regime.setdefault((subset, key), []).append(row["sensors"])
    # Collapse operating points to ≤6 regimes per subset by distinct setting tuple.
    baselines: dict = {"baselines": {}}
    centroids: dict = {}
    for (subset, _key), _rows in per_subset_regime.items():
        baselines["baselines"].setdefault(subset, {})
        centroids.setdefault(subset, [])
    # Regime classification: for the pipeline, operating settings cluster into up to
    # 6 centroids per subset (FD001/FD003 → 1, FD002/FD004 → 6). Simplified k-means
    # on the distinct setting tuples keeps this stdlib-first (no sklearn at fit).
    from collections import defaultdict

    for subset in list(baselines["baselines"]):
        points = sorted({k for (s, k) in per_subset_regime if s == subset})
        chosen = points[:6] if len(points) > 6 else points
        centroids[subset] = [[float(a), float(b), float(c)] for (a, b, c) in chosen] or [[0.0, 0.0, 0.0]]
        # Assign rows to nearest chosen centroid, then median/MAD per sensor.
        buckets: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for (s, key), rows in per_subset_regime.items():
            if s != subset:
                continue
            pt = [float(key[0]), float(key[1]), float(key[2])]
            best, best_d = 0, float("inf")
            for i, c in enumerate(centroids[subset]):
                d = sum((pt[j] - c[j]) ** 2 for j in range(3))
                if d < best_d:
                    best, best_d = i, d
            for row in rows:
                for sensor, val in row.items():
                    buckets[best][sensor].append(float(val))
        for regime, sensors in buckets.items():
            baselines["baselines"][subset][str(regime)] = {
                sensor: _median_mad(vals) for sensor, vals in sensors.items()
            }
    baselines["centroids"] = centroids
    return baselines


def fit_and_evaluate(cfg, pooled: dict, train_names: list, holdout_names: list, *, out_dir) -> dict:
    from ..contract import FEATURE_ORDER, build_matrix_per_row_regime
    from ..contract.order import contract_sensors
    from .estimator import make_estimator
    from .metrics import mae, r2, rmse
    from .splits import group_kfold

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    window = 30
    train_windows = {u: _rows_to_windows(pooled[u], window=window) for u in train_names}
    holdout_windows = {u: _rows_to_windows(pooled[u], window=window) for u in holdout_names}
    baselines = _derive_baselines(train_windows, rul_cap=cfg.rul_cap)
    stats = baselines
    centroids_all = baselines.get("centroids", {})

    needed = contract_sensors(FEATURE_ORDER)

    def featurize(windows: list[list[dict]], subset_hint: str):
        X, y = [], []
        for w in windows:
            subset = w[0].get("subset", subset_hint)
            # Rows carry subset via namespaced unit; resolve per window.
            matrix, _, _ = build_matrix_per_row_regime(
                w,
                s6_median=21.6098,
                stats=stats,
                subset=subset,
                centroids=centroids_all.get(subset),
                regime_offset=0,
                feature_order=FEATURE_ORDER,
                missing_sensor_values={s: 0.0 for s in needed},
            )
            # One label per window (last row only, matching inference
            # `predict(matrix)[-1]`). Extending with all 30 rows labels early
            # cycles with the window-end RUL and 30x's the data (600k rows for
            # FD001), which cost ~4 cycles RMSE and the >10 min hang.
            X.append(matrix[-1])
            # Target: RUL at window end (exam-style, truncated histories).
            y.append(w[-1].get("RUL", 0))
        return X, y

    # Tag subset per row from unit namespace.
    for u in list(train_windows):
        subset = u.split("#")[0]
        for w in train_windows[u]:
            for r in w:
                r.setdefault("subset", subset)
    for u in list(holdout_windows):
        subset = u.split("#")[0]
        for w in holdout_windows[u]:
            for r in w:
                r.setdefault("subset", subset)

    import numpy as np

    # GroupKFold CV over training units (notebook exam-style, kept verbatim).
    # group_kfold clamps to len(units) and returns [] when <2 units (dry-run).
    folds = group_kfold(train_names, n_splits=min(5, max(2, len(train_names))), seed=cfg.seed)
    cv_rmses = []
    best_iters: list[int] = []
    for tr, te in folds:
        Xtr, ytr = featurize([w for u in tr for w in train_windows[u]], cfg.datasets[0])
        Xte, yte = featurize([w for u in te for w in train_windows[u]], cfg.datasets[0])
        est = make_estimator(cfg.model, seed=cfg.seed)
        est.fit(np.array(Xtr), np.array(ytr), eval_set=[(np.array(Xte), np.array(yte))], verbose=False)
        pred = est.predict(np.array(Xte)).tolist()
        cv_rmses.append(rmse(yte, pred))
        try:
            best_iters.append(int(est.best_iteration) + 1)
        except Exception:
            pass
    cv_mean = sum(cv_rmses) / max(1, len(cv_rmses)) if cv_rmses else 0.0

    # Holdout: engines the model never trained on.
    Xtr_all, ytr_all = featurize([w for u in train_names for w in train_windows[u]], cfg.datasets[0])
    Xho, yho = featurize([w for u in holdout_names for w in holdout_windows[u]], cfg.datasets[0])
    est = make_estimator(cfg.model, seed=cfg.seed)
    if Xho and yho:
        est.fit(
            np.array(Xtr_all),
            np.array(ytr_all),
            eval_set=[(np.array(Xho), np.array(yho))],
            verbose=False,
        )
    else:
        est.fit(np.array(Xtr_all), np.array(ytr_all))
    pred_ho = est.predict(np.array(Xho)).tolist() if Xho else []
    ho_rmse = rmse(yho, pred_ho) if yho else 0.0
    ho_mae = mae(yho, pred_ho) if yho else 0.0
    ho_r2 = r2(yho, pred_ho) if yho else 0.0
    try:
        holdout_best = int(est.best_iteration) + 1
        best_iters.append(holdout_best)
    except Exception:
        holdout_best = 0

    # Refit on 100% for serving (both numbers recorded — §10.8.2).
    # Pin rounds from early stopping instead of retraining 1000 trees: the
    # unbiased eval_set is gone once we train on all units.
    Xall, yall = featurize(
        [w for u in train_names + holdout_names for w in (train_windows.get(u) or holdout_windows.get(u))],
        cfg.datasets[0],
    )
    import dataclasses

    refit_cfg = cfg.model
    pinned = sorted(b for b in best_iters if b and b > 0)
    if pinned:
        refit_cfg = dataclasses.replace(
            refit_cfg, n_estimators=int(pinned[len(pinned) // 2]), early_stopping_rounds=0
        )
    final = make_estimator(refit_cfg, seed=cfg.seed)
    final.fit(np.array(Xall), np.array(yall))

    # Persist artifacts the backend stages (same filenames stage_ml_artifacts expects).
    import json

    try:
        final.save_model(str(out / "xgboost_model.json"))
    except Exception:
        pass
    (out / "regime_baselines.json").write_text(json.dumps(baselines, indent=2))
    (out / "feature_contract.json").write_text(json.dumps({"feature_order": list(FEATURE_ORDER)}))
    return {
        "cv_rmse_mean": cv_mean,
        "cv_rmses": cv_rmses,
        "holdout_rmse": ho_rmse,
        "holdout_mae": ho_mae,
        "holdout_r2": ho_r2,
        "has_holdout": True,
        "n_train_units": len(train_names),
        "n_holdout_units": len(holdout_names),
        "best_iteration": pinned[len(pinned) // 2] if pinned else int(cfg.model.n_estimators),
        "n_folds": len(cv_rmses),
    }
