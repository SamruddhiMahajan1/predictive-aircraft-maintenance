# Model card — RUL booster (docs/16 §10.9)

## Dataset
NASA C-MAPSS FD001–FD004 (train/test/RUL txt). Default replay + shipped artifact: FD001.
Row counts enforced by `rul validate` (`rul/data/schema.py`): FD001 20631/13096,
FD002 53759/16796, FD003 24720/16496, FD004 61249/25149.

## Target
Remaining useful life, capped at 125 (`rul_cap`). `cycle` is deliberately excluded
as a feature — it correlates only via test-set truncation.

## Features
`rul.contract` is the single source of truth (`FEATURE_ORDER`, rolling window 5,
ddof=0, per-regime robust z-score `z = (v - median) / max(mad, 1e-6)`, per-row regime
classification). Training and serving import the same functions; `MAD_REL_FLOOR`
(median-proportional) is gone.

Two subtleties the artifact itself forced:

- The floor is on the **divisor**, not the result. Zero-MAD sensors (s6/s10/s16
  healthy windows read bitwise-constant) trained to `(v - median)/1e-6` magnitudes —
  the booster splits `s10` at 0/30000, `s16` at 10000, `s6` at −70000. Substituting
  0.0 there feeds "healthy" where training saw ±30000.
- The pooled contract scores **17 sensors**: s10/s16 are constant in FD001 but vary
  in FD002/FD003/FD004, and the read path must carry their raw values on those
  subsets (dropping them fed 0.0-raw → FD003 served 22.5 vs 20.2 training-true).

## Split
GroupShuffleSplit/GroupKFold on namespaced `unit` (`FDxxx#n`), overlap-asserted.
Holdout by group is reported, then refit on 100% for serving — both numbers recorded
in `runs/<id>/metrics.json` (`has_holdout: true` for pipeline runs).

## Metrics
Gates (docs/08): MAE ≤ 14, RMSE ≤ 20, R² ≥ 0.80 — against MEASURED predictions.
Shipped artifact (notebook): FD001 official-test RMSE 17.942 / MAE 13.079
(reproduced exactly by the §4 harness); as served before the MAD fix 18.290/13.393
(+0.700 optimistic bias, now removed).

Serving-vs-training equivalence, measured through the real serving path
(`predict()` + booster, official test final-cycle vs `RUL_FD*.txt`, Oct 2026):

| Subset | As served now | Claimed | Status |
|---|---|---:|---|
| FD001 | 17.954 / 13.060 | 17.942 / 13.079 | match (Δ 0.012) |
| FD002 | 28.309 | 28.318 | match — model genuinely weak on 6-regime data |
| FD003 | 20.154 | 20.175 | match (was 22.5 before the s10 fix) |
| FD004 | 30.228 | 30.215 | match — same 6-regime gap as FD002 |

## Known limitations
- FD002/FD004 score RMSE ~28–30 through the serving path **and** in training —
  the gap is modeling (6-regime data, single pooled booster), not serving skew.
  Verified by serving==claimed on all four subsets (table above). Improving it needs
  better features/modeling for multi-regime data, not another skew fix.
- Shipped `metrics_all_full.json` reports `has_holdout: false` — its CV numbers
  belong to five other boosters. Pipeline runs record the real holdout.
- Stale docs quoting the FD001-only candidate CV (17.988 ± 1.487) vs shipped
  (17.369 ± 0.950) are being corrected to point here.
- Thresholds `MISSION_READY_MIN_RUL=30`, `Z_*` anchors: calibrated constants with
  measured derivation in `inference.py`; 3.89% mission-ready misclassification sits
  inside the model's noise band — see conformal intervals (Phase 6.1, planned).

## Serving-path equivalence
`ml/tests/test_contract.py` asserts training path == serving path (contract parity);
`backend/tests/ml/test_model_quality.py` golden test fails if `MAD_REL_FLOOR` returns.
