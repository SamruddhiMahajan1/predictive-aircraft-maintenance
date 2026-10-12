"""Promotion gate (docs/16 §10.4). Refuses a run unless gates pass, manifest is
complete, and the artifact's contract matches rul.contract FEATURE_ORDER."""

from __future__ import annotations

import json
from pathlib import Path


def can_promote(run_dir: str | Path) -> tuple[bool, list[str]]:
    rd = Path(run_dir)
    reasons: list[str] = []
    try:
        metrics = json.loads((rd / "metrics.json").read_text())
        manifest = json.loads((rd / "manifest.json").read_text())
        config = json.loads((rd / "config.json").read_text())
    except FileNotFoundError as exc:
        return False, [f"missing registry file: {exc.filename}"]
    if metrics.get("gate_failures"):
        reasons.append(f"gates failed: {metrics['gate_failures']}")
    if manifest.get("git_sha") in (None, "unknown", ""):
        reasons.append("manifest lacks git SHA")
    if not manifest.get("inputs"):
        reasons.append("manifest lacks data manifest")
    try:
        from ..contract import FEATURE_ORDER

        contract = json.loads((rd / "feature_contract.json").read_text()) if (rd / "feature_contract.json").exists() else None
        if contract is not None and list(contract.get("feature_order", [])) != list(FEATURE_ORDER):
            reasons.append("artifact contract != rul.contract FEATURE_ORDER (drift)")
    except Exception as exc:
        reasons.append(f"contract check failed: {exc}")
    _ = config
    return (not reasons), reasons


__all__ = ["can_promote"]
