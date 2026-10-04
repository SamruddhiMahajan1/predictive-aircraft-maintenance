# Model artifacts

**This directory is empty and unused.** The trained artifacts are staged in
`data/ml/<variant>/`, which is what the loader reads.

It previously held a README describing three files — `rul_xgb.json`,
`feature_manifest.json`, `baseline_stats.json` — specified by `docs/08 §4`. Those were
never produced by `scripts/train_rul.py`, and the 22-feature contract they were written
against is obsolete. Nothing reads this directory.

## Where the artifacts actually are

```
backend/data/ml/
├── all/                        SERVING variant (FDT_ML_VARIANT=all)
│   ├── xgboost_all_full.json           pooled booster, 709 engines, 161 rounds
│   ├── feature_contract_all_full.json  32 features + regime_column + baselines filename
│   ├── regime_baselines_all.json       per-subset per-regime median/MAD, centroids, offsets
│   └── metrics_all_full.json           CV metrics (reporting only)
├── full/                       FD001-only refit (29 features) — optional
└── holdout/                    Phase 1 80/20 model + StandardScaler — optional
```

`data/ml/` is gitignored. Stage artifacts with:

```bash
python -m scripts.stage_ml_artifacts --source <dir> --variant all
```

The script discovers the required file set from the contract rather than hardcoding it,
and refuses to stage a booster whose feature count disagrees with the contract — the one
check worth doing at staging time, because XGBoost consumes a positional matrix and a
mismatched pair yields plausible-looking wrong predictions rather than an error.

## Which variant to serve

| Variant | Width | Trained on | Notes |
|---|---:|---|---|
| `all` | 32 | FD001+FD002+FD003+FD004, 709 engines | **default.** Keeps `s10`/`s16` + `regime_global` |
| `full` | 29 | FD001 only, 100 engines | Simpler contract; single regime |
| `holdout` | 29 | FD001 80/20 | Ships a `StandardScaler`; the only variant with one |

Select with `FDT_ML_VARIANT`, never by pinning `FDT_ML_MODEL_PATH` — that overrides only
the model and leaves the contract to resolve from the variant, so the two disagree about
which directory the artifact set lives in. See `docs/15`.

## The 32-column pooled contract

The pooled candidate is **32 features, not 30 and not 29**:

```
op1, op2                                     2   operating settings
s2..s21 (15)                                15   sensors measured in FD001
s11/s4/s9/s12/s14/s7 rollmean+rollstd       12   rolling mean AND std
regime_global                                1   absolute operating-condition id
s10, s16                                     2   constant in FD001, live in FD002/FD004
```

`s10` and `s16` are the part that breaks naive implementations. They are constant in
FD001, so FD001 telemetry never carries them and FD001's baseline block omits them — yet
the booster expects both columns. They hold 0.32 % of total gain combined and have
`mad: 0.0` in every subset, so they are constants: a z-score of a constant is 0.0 by
definition. See `docs/15` §3 for how the backend supplies them.

## If the artifacts are absent

The app still boots: inference falls back to the deterministic `rul = 125 − cycle` and
every response carries `model.fallback: true` with a `reason`. The feature-count
assertion (`booster.num_features() == contract.n_features`) raises
`ModelUnavailableError` rather than serving wrong predictions. `/healthz` reports
`model.degraded: true` and `status: degraded`.