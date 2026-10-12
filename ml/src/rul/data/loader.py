"""C-MAPSS loader: raw txt -> per-unit cycle rows the contract consumes.

Unit ids are namespaced `FDxxx#n` before any pooled split so a unit 7 in FD001
can never collide with unit 7 in FD003 (notebook leakage discipline, kept verbatim).
`cycle` is never emitted as a feature — see contract/order.py.
"""

from __future__ import annotations

from pathlib import Path

SENSOR_COLS = [f"s{i}" for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)]
# C-MAPSS column layout: unit, cycle, 3 settings, 21 sensors
KEPT_SENSORS = ("s2", "s3", "s4", "s6", "s7", "s8", "s9", "s10", "s11", "s12", "s13", "s14", "s15", "s16", "s17", "s20", "s21")


def load_subset(cmapss_dir: str | Path, subset: str, *, kind: str = "train", rul_cap: int = 125) -> dict:
    """{namespaced_unit: [{cycle, settings, sensors}]}. RUL capped at rul_cap."""
    d = Path(cmapss_dir)
    path = d / f"{kind}_{subset}.txt"
    rul_path = d / f"RUL_{subset}.txt" if kind == "test" else None
    rul_truth: list[int] = []
    if rul_path is not None and rul_path.exists():
        rul_truth = [int(float(tok.split()[0])) for tok in rul_path.read_text().split() if tok.strip()]
    units: dict[str, list[dict]] = {}
    max_cycle: dict[str, int] = {}
    with path.open() as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            unit = int(float(parts[0]))
            cycle = int(float(parts[1]))
            key = f"{subset}#{unit}"
            settings = {"setting_1": float(parts[2]), "setting_2": float(parts[3]), "setting_3": float(parts[4])}
            sensors = {f"s{i}": float(parts[5 + i - 1]) for i in range(1, 22) if f"s{i}" in KEPT_SENSORS}
            units.setdefault(key, []).append({"cycle": cycle, "settings": settings, "sensors": sensors})
            max_cycle[key] = max(max_cycle.get(key, 0), cycle)
    # Attach capped RUL: train = max_cycle - cycle; test = truth + (max - cycle).
    for key, rows in units.items():
        rows.sort(key=lambda r: r["cycle"])
        if kind == "train":
            mc = max_cycle[key]
            for r in rows:
                r["RUL"] = min(rul_cap, mc - r["cycle"])
        else:
            idx = int(key.split("#")[1]) - 1
            truth = rul_truth[idx] if idx < len(rul_truth) else 0
            mc = max_cycle[key]
            for r in rows:
                r["RUL"] = min(rul_cap, truth + (mc - r["cycle"]))
    return units


__all__ = ["load_subset", "KEPT_SENSORS"]
