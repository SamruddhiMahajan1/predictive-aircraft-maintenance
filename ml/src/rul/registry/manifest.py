"""Local run registry (docs/16 §10.4). Replaces 'trust the JSON'.

Every run writes runs/<run_id>/{config.json, manifest.json, metrics.json,
report.md} plus an append-only runs/index.jsonl — greppable, diffable. Ties
every metric to the exact artifact it describes, with data hash + code SHA.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _lib_versions() -> dict:
    out = {}
    for mod in ("python", "xgboost", "sklearn", "numpy"):
        try:
            if mod == "python":
                import sys

                out[mod] = sys.version.split()[0]
            else:
                out[mod] = __import__(mod).__version__
        except Exception:
            out[mod] = "unknown"
    out["platform"] = platform.platform()
    return out


def write_run(runs_dir: str | Path, *, config: dict, metrics: dict, artifacts: dict, seed: int) -> Path:
    runs = Path(runs_dir)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"_s{seed}"
    rd = runs / run_id
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True))
    manifest = {
        "run_id": run_id,
        "utc": datetime.now(UTC).isoformat(),
        "seed": seed,
        "git_sha": _git_sha(),
        "versions": _lib_versions(),
        "inputs": metrics.get("data_sha256", {}),
        "artifacts": {},
    }
    for name, p in artifacts.items():
        pp = Path(p)
        if pp.exists():
            h = hashlib.sha256()
            with pp.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            manifest["artifacts"][name] = {"path": str(pp), "sha256": h.hexdigest()}
    (rd / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    (rd / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True))
    report = [
        f"# Run {run_id}",
        "",
        f"- config: {config.get('name')} seed={seed}",
        f"- git: {manifest['git_sha']}",
        f"- cv_rmse: {metrics.get('cv_rmse_mean')} holdout_rmse: {metrics.get('holdout_rmse')}",
        f"- gates: {metrics.get('gate_failures') or 'PASS'}",
    ]
    (rd / "report.md").write_text("\n".join(report) + "\n")
    with (runs / "index.jsonl").open("a") as f:
        f.write(json.dumps({"run_id": run_id, **metrics, "git_sha": manifest["git_sha"]}) + "\n")
    return rd


__all__ = ["write_run"]
