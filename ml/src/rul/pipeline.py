"""Pipeline entry: config -> train -> registry (docs/16 §10)."""

from __future__ import annotations

from pathlib import Path


def run_pipeline(*, config_path, cmapss_dir, runs_dir, out_dir=None, dry_run: bool = False) -> Path:
    from .config import load_config
    from .modeling.train import train_config
    from .registry.manifest import write_run

    cfg = load_config(config_path)
    out = Path(out_dir) if out_dir else Path(runs_dir) / "_staging" / cfg.name
    metrics = train_config(cfg, cmapss_dir=str(cmapss_dir), out_dir=str(out), dry_run=dry_run)
    artifacts = {
        "model": out / "xgboost_model.json",
        "baselines": out / "regime_baselines.json",
        "contract": out / "feature_contract.json",
    }
    rd = write_run(runs_dir, config=cfg.resolved_dict(), metrics=metrics, artifacts={k: str(v) for k, v in artifacts.items()}, seed=cfg.seed)
    # Copy staged artifacts into the run dir so promotion is self-contained.
    import shutil

    for p in out.iterdir():
        shutil.copy(p, rd / p.name)
    return rd


__all__ = ["run_pipeline"]
