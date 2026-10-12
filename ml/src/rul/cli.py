"""`python -m rul` CLI: download | validate | train | promote (docs/16 §10.7)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_download(args) -> int:
    from .data.acquire import download

    download(subset_all=args.subset_all)
    return 0


def _cmd_validate(args) -> int:
    from .data.schema import validate_subset

    if args.fixture:
        print("fixture: schema module importable; no data required")
        return 0
    report = validate_subset(args.cmapss_dir, args.subset)
    print(json.dumps(report, indent=2))
    return 0


def _cmd_train(args) -> int:
    from .pipeline import run_pipeline

    rd = run_pipeline(
        config_path=args.config,
        cmapss_dir=args.cmapss_dir,
        runs_dir=args.runs_dir,
        dry_run=args.dry_run,
    )
    print(f"run: {rd}")
    if not args.dry_run:
        from .registry.promote import can_promote

        ok, reasons = can_promote(rd)
        print("promote:", "OK" if ok else "; ".join(reasons))
        return 0 if ok else 2
    return 0


def _cmd_promote(args) -> int:
    from .registry.promote import can_promote

    ok, reasons = can_promote(args.run_dir)
    print("promote:", "OK" if ok else "; ".join(reasons))
    if ok and args.stage_to:
        import shutil

        dest = Path(args.stage_to)
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("xgboost_model.json", "regime_baselines.json", "feature_contract.json"):
            src = Path(args.run_dir) / name
            if src.exists():
                shutil.copy(src, dest / name)
    return 0 if ok else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rul")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--subset-all", action="store_true")
    d.set_defaults(fn=_cmd_download)
    v = sub.add_parser("validate")
    v.add_argument("--cmapss-dir", default="backend/data/cmapss")
    v.add_argument("--subset", default="FD001")
    v.add_argument("--fixture", action="store_true")
    v.set_defaults(fn=_cmd_validate)
    t = sub.add_parser("train")
    t.add_argument("--config", required=True)
    t.add_argument("--cmapss-dir", default="backend/data/cmapss")
    t.add_argument("--runs-dir", default="ml/runs")
    t.add_argument("--dry-run", action="store_true")
    t.set_defaults(fn=_cmd_train)
    pr = sub.add_parser("promote")
    pr.add_argument("run_dir")
    pr.add_argument("--stage-to", default=None)
    pr.set_defaults(fn=_cmd_promote)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
