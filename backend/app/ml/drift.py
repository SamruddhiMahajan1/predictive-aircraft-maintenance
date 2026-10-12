"""Baseline-drift sentinel (docs/16 §11.2). Catches the bug CLASS, not the bug.

Watches live input statistics against the shipped regime_baselines artifact and
surfaces divergence on /healthz and ModelBadge. When s8's served variance collapses
to zero — as in C2 — the system SAYS so rather than quietly getting worse.

State-free pure check: given recent raw values per sensor and the baseline block,
report sensors whose live spread collapsed while the baseline says they move.
"""

from __future__ import annotations

from typing import Any


def check_drift(
    recent: dict[str, list[float]],
    baseline: dict[str, Any],
    *,
    min_samples: int = 20,
    collapse_ratio: float = 0.05,
) -> list[dict[str, Any]]:
    """Sensors whose live MAD collapsed vs the shipped baseline MAD.

    recent: sensor -> last N raw values (N >= min_samples to report).
    baseline: regime_block(sensor -> {median, mad}).
    A sensor flags when baseline MAD > eps but live spread < collapse_ratio * MAD —
    exactly the C2 signature (served z=0 forever while training saw |z|→12.5).
    """
    findings: list[dict[str, Any]] = []
    for sensor, vals in recent.items():
        if len(vals) < min_samples:
            continue
        stat = baseline.get(sensor)
        if not stat:
            continue
        base_mad = float(stat.get("mad", 0.0) or 0.0)
        if base_mad <= 1e-6:
            continue  # constant in this subset's baselines (FD001's s10/s16) — never flags
        ordered = sorted(vals)
        mid = len(ordered) // 2
        median = ordered[mid]
        live_mad = sorted(abs(v - median) for v in ordered)[mid]
        if live_mad < base_mad * collapse_ratio:
            findings.append(
                {
                    "sensor": sensor,
                    "baseline_mad": round(base_mad, 4),
                    "live_mad": round(live_mad, 4),
                    "reason": "served variance collapsed vs shipped baseline",
                }
            )
    return findings


__all__ = ["check_drift"]
