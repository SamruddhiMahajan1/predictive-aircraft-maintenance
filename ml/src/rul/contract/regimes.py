"""Regime baselines and nearest-centroid classification.

Both routines walk an artifact document of unknown shape. Four baseline layouts exist in
the wild and guessing wrong is silent -- an empty block reads as "no sensor deviates",
i.e. every component perfectly healthy:

    Phase 1           {"regime_0": {sensor: {median, mad}}}
    Phase 2 (flat)    {"baselines": {"0": {sensor: ...}}}
    Phase 2 (shipped) {"baselines": {"FD001": {"0": {sensor: ...}}}}   <- subset level
    legacy            {"0": {sensor: ...}}

Rather than enumerate every shape, walk the document and return the first block that
actually looks like sensor statistics, preferring the requested subset and regime.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def classify_regime(settings_row: dict[str, float], centroids: Any | None) -> int:
    """Nearest centroid on the operating settings. FD001 has a single regime."""
    if not centroids:
        return 0
    rows: list[Sequence[float]]
    if isinstance(centroids, dict):
        flat: list[Sequence[float]] = []
        for value in centroids.values():
            if isinstance(value, dict):
                flat.append([float(v) for v in value.get("settings", {}).values()])
            else:
                flat.append([float(x) for x in value])
        rows = flat
    else:
        rows = [[float(x) for x in row] for row in centroids]

    if not rows:
        return 0
    width = len(rows[0])
    s = [
        float(settings_row.get(k, 0.0))
        for k in ("setting_1", "setting_2", "setting_3", "op1", "op2", "op3")
    ][:width]
    s += [0.0] * (width - len(s))

    best, best_d = 0, float("inf")
    for i, centroid in enumerate(rows):
        d = sum((s[j] - centroid[j]) ** 2 for j in range(width))
        if d < best_d:
            best, best_d = i, d
    return int(best)


def regime_block(
    stats: dict[str, Any], regime: int = 0, subset: str | None = None
) -> dict[str, Any]:
    """Find the per-sensor baseline block for `regime`, whatever the nesting."""
    preferred = [f"regime_{regime}", str(regime), regime]
    if subset:
        preferred = [f"{subset}::{key}" for key in preferred] + preferred

    for key in preferred:
        value = _dig(stats, key)
        if _is_sensor_block(value):
            return dict(value)

    # subset level: baselines[subset][regime]
    baselines = stats.get("baselines")
    if isinstance(baselines, dict):
        names = list(baselines)
        subset_level = bool(names) and all(
            _is_sensor_block(_dig(baselines.get(n) or {}, str(regime))) for n in names
        )
        if subset is not None and subset_level and subset not in baselines:
            # Requested subset named and absent: return nothing rather than another
            # subset's baseline. An empty block is caught upstream (deviation becomes
            # empty, health is flagged); silently using FD001's medians while the
            # request said FD004 is the failure mode this whole path exists to stop.
            return {}
        for name in ([subset] if subset in baselines else names):
            block = _dig(baselines.get(name) or {}, str(regime))
            if _is_sensor_block(block):
                return dict(block)

    # Last resort. Bounded, and only ever reached when nothing above matched -- which is
    # precisely the situation where "some other subset's baseline" is the wrong answer
    # to give. So it is bounded to the requested subset where the document allows it.
    if subset is not None:
        scoped = _find_sensor_block_in(stats, subset, depth=3)
        if scoped is not None:
            return scoped
    return _find_sensor_block(stats, depth=3) or {}


def _dig(mapping: Any, key: Any) -> Any:
    return mapping.get(key) if isinstance(mapping, dict) else None


def _is_sensor_block(value: Any) -> bool:
    """A baseline block is a dict of sensors that each carry median/mad."""
    if not isinstance(value, dict) or not value:
        return False
    sample = next(iter(value.values()))
    return isinstance(sample, dict) and "median" in sample and "mad" in sample


def _find_sensor_block(node: Any, depth: int) -> dict[str, Any] | None:
    if depth <= 0 or not isinstance(node, dict):
        return None
    if _is_sensor_block(node):
        return node
    for value in node.values():
        if isinstance(value, dict):
            found = _find_sensor_block(value, depth - 1)
            if found:
                return found
    return None


def _find_sensor_block_in(node: Any, subset: str, depth: int) -> dict[str, Any] | None:
    """Search only the subtree named `subset`.

    The unscoped search above is a fallback for documents that do not name subsets at
    all. When the document *does* name the subset the caller asked for, an unscoped walk
    can leave that subtree and return a block belonging to some other one -- which is
    the exact defect this function exists to prevent, so the fallback is constrained to
    the requested subset whenever it is present at all.
    """
    if depth <= 0 or not isinstance(node, dict):
        return None
    branch = node.get(subset)
    if branch is not None:
        found = _find_sensor_block(branch, depth)
        if found is not None:
            return found
    for value in node.values():
        if isinstance(value, dict) and subset in value:
            found = _find_sensor_block_in(value, subset, depth - 1)
            if found:
                return found
    return None


__all__ = ["classify_regime", "regime_block"]