"""Phase 0 — finalise the C-MAPSS RUL model and emit the artifacts (docs/08 §4).

    python scripts/train_rul.py --dataset FD001 --seed 42 --out models_artifacts/

Emits rul_xgb.json, feature_manifest.json and baseline_stats.json. Refuses to
overwrite a better artifact unless --force.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor

COLUMNS = (
    ["unit_id", "cycle", "setting_1", "setting_2", "setting_3"]
    + [f"sensor_{i}" for i in range(1, 22)]
)
CONSTANT_FD001 = ["setting_3", "sensor_1", "sensor_5", "sensor_10",
                  "sensor_16", "sensor_18", "sensor_19"]
SENSORS = ["s2", "s3", "s4", "s6", "s7", "s8", "s9", "s11",
           "s12", "s13", "s14", "s15", "s17", "s20", "s21"]
ROLLING = ["s11", "s4", "s9", "s12", "s14", "s7"]
FEATURE_ORDER = ["cycle"] + SENSORS + [f"{s}_roll5" for s in ROLLING]


def load(path: Path) -> dict[str, np.ndarray]:
    data = np.loadtxt(path)
    return {name: data[:, i] for i, name in enumerate(COLUMNS)}


def engineer(df: dict[str, np.ndarray]) -> np.ndarray:
    n = len(df["unit_id"])
    out = np.column_stack([df["cycle"]] + [df[f"sensor_{s[1:]}"] for s in SENSORS])
    for sensor in ROLLING:
        col = df[f"sensor_{sensor[1:]}"]
        means = np.zeros(n)
        for unit in np.unique(df["unit_id"]):
            mask = df["unit_id"] == unit
            means[mask] = _rolling_mean(col[mask], 5)
        out = np.column_stack([out, means])
    return out


def _rolling_mean(series: np.ndarray, window: int) -> np.ndarray:
    out = np.empty_like(series, dtype=float)
    for i in range(len(series)):
        start = max(0, i - window + 1)
        out[i] = series[start:i + 1].mean()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="FD001")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data", default="data/cmapss")
    parser.add_argument("--out", default="models_artifacts")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    train = load(Path(args.data) / f"train_{args.dataset}.txt")
    test = load(Path(args.data) / f"test_{args.dataset}.txt")
    max_cycles = {u: c.max() for u, c in
                  ((u, train["cycle"][train["unit_id"] == u])
                   for u in np.unique(train["unit_id"]))}
    rul = np.array([max_cycles[u] - c
                for u, c in zip(train["unit_id"], train["cycle"], strict=True)])

    x_train = engineer(train)
    units = np.unique(train["unit_id"])
    train_units, val_units = train_test_split(units, test_size=0.20, random_state=args.seed)

    tr_mask = np.isin(train["unit_id"], train_units)
    va_mask = np.isin(train["unit_id"], val_units)

    model = XGBRegressor(objective="reg:squarederror", n_estimators=500,
                         learning_rate=0.05, max_depth=6, subsample=0.8,
                         colsample_bytree=0.8, random_state=args.seed, n_jobs=-1)
    model.fit(x_train[tr_mask], rul[tr_mask])
    pred = model.predict(x_train[va_mask])
    actual = rul[va_mask]

    mae = float(np.abs(pred - actual).mean())
    rmse = float(np.sqrt(((pred - actual) ** 2).mean()))
    r2 = float(1 - ((pred - actual) ** 2).sum() / ((actual - actual.mean()) ** 2).sum())
    print(f"validation (engine-level split)\n  MAE  : {mae:.4f}\n  RMSE : {rmse:.4f}\n  R2   : {r2:.4f}")

    # official test-set score, when RUL_FDxxx.txt is present
    rul_file = Path(args.data) / f"RUL_{args.dataset}.txt"
    if rul_file.exists():
        x_test = engineer(test)
        official = np.loadtxt(rul_file)
        units = np.unique(test["unit_id"])
        last = {u: test["cycle"][test["unit_id"] == u].max() for u in units}
        keep = [i for i, u in enumerate(units) if last[u] > 0]
        truth = np.array([official[i] for i in keep])
        pred = model.predict(x_test[keep])
        test_mae = float(np.abs(pred - truth).mean())
        print(f"official test set\n  MAE  : {test_mae:.4f}")

    out = Path(args.out)
    manifest_path = out / "feature_manifest.json"
    if manifest_path.exists() and not args.force:
        old = json.loads(manifest_path.read_text())
        if old.get("metrics", {}).get("mae", 0) < mae:
            print(f"existing MAE {old['metrics']['mae']} is better — not overwriting "
                  f"(use --force)")
            return 1

    out.mkdir(parents=True, exist_ok=True)
    model.save_model(out / "rul_xgb.json")

    importance = model.get_booster().get_score(importance_type="gain")
    manifest = {
        "version": f"rul_xgb_{args.dataset.lower()}",
        "dataset": args.dataset,
        "n_features": len(FEATURE_ORDER),
        "feature_order": FEATURE_ORDER,
        "sensors": SENSORS,
        "rolling": {"sensors": ROLLING, "window": 5},
        "constant_dropped": CONSTANT_FD001,
        "regimes": 1,
        "metrics": {"mae": round(mae, 4), "rmse": round(rmse, 4), "r2": round(r2, 4)},
        "importance": dict(sorted(importance.items(), key=lambda kv: -kv[1])),
        "rul_cap": 125,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))

    # robust baseline: median + MAD over each unit's first 20 healthy cycles
    stats = {"version": manifest["version"], "healthy_window_cycles": 20, "regime_0": {}}
    for sensor in SENSORS:
        col = train[f"sensor_{sensor[1:]}"]
        baseline = []
        for unit in np.unique(train["unit_id"]):
            mask = train["unit_id"] == unit
            order = np.argsort(train["cycle"][mask])
            baseline.extend(col[mask][order][:20])
        baseline = np.array(baseline)
        mad = float(np.median(np.abs(baseline - np.median(baseline))))
        stats["regime_0"][sensor] = {"median": round(float(np.median(baseline)), 4),
                                     "mad": round(mad, 6)}
    (out / "baseline_stats.json").write_text(json.dumps(stats, indent=2))

    print(f"wrote {out}/rul_xgb.json, feature_manifest.json, baseline_stats.json")
    return 0 if mae <= 25.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
