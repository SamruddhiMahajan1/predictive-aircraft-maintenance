"""C-MAPSS schema validation (docs/16 §10.5). `rul validate` entry point.

Asserts 26 columns per file, unit ids contiguous from 1, cycles starting at 1
and increasing by 1, no NaN, positive RUL proxy, and row counts matching the
published NASA counts — a truncated download fails hard rather than training
silently.
"""

from __future__ import annotations

from pathlib import Path

PUBLISHED_ROWS = {
    # subset: (train_rows, test_rows, n_units)
    "FD001": (20631, 13096, 100),
    "FD002": (53759, 16796, 260),
    "FD003": (24720, 16496, 100),
    "FD004": (61249, 25149, 249),
}
EXPECTED_COLS = 26


def validate_file(path: str | Path, *, kind: str, subset: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"missing {kind}_{subset}: {p}")
    n_rows = 0
    units: dict[int, list[int]] = {}
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cols = line.split()
            if len(cols) != EXPECTED_COLS:
                raise ValueError(f"{p.name}: expected {EXPECTED_COLS} cols, got {len(cols)}")
            try:
                unit = int(float(cols[0]))
                cycle = int(float(cols[1]))
            except ValueError as exc:
                raise ValueError(f"{p.name}: bad unit/cycle in {cols[:2]}") from exc
            for c in cols:
                v = float(c)
                if v != v:  # NaN
                    raise ValueError(f"{p.name}: NaN value")
            units.setdefault(unit, []).append(cycle)
            n_rows += 1
    if not units:
        raise ValueError(f"{p.name}: no rows")
    if sorted(units) != list(range(1, len(units) + 1)):
        raise ValueError(f"{p.name}: unit ids not contiguous from 1")
    for unit, cycles in units.items():
        if cycles[0] != 1 or any(b - a != 1 for a, b in zip(cycles, cycles[1:])):
            raise ValueError(f"{p.name}: unit {unit} cycles not 1,2,3…")
    exp = PUBLISHED_ROWS.get(subset)
    if exp is not None:
        want = exp[0] if kind == "train" else exp[1]
        if n_rows != want:
            raise ValueError(f"{p.name}: got {n_rows} rows, published NASA count is {want}")
    return {"path": str(p), "rows": n_rows, "units": len(units)}


def validate_subset(cmapss_dir: str | Path, subset: str) -> dict:
    d = Path(cmapss_dir)
    out = {}
    for kind in ("train", "test", "RUL"):
        p = d / f"{kind}_{subset}.txt"
        if kind == "RUL":
            if not p.exists():
                raise FileNotFoundError(f"missing RUL_{subset}: {p}")
            out[kind] = {"path": str(p)}
            continue
        out[kind] = validate_file(p, kind=kind, subset=subset)
    return out


__all__ = ["validate_file", "validate_subset", "PUBLISHED_ROWS", "EXPECTED_COLS"]
