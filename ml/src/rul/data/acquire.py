"""Dataset acquisition wrapper (docs/16 §10.5). `rul download` entry point.

Wraps scripts/fetch-cmapss.sh so training never depends on a shell script being
remembered — same URLs, same row-count enforcement, verified checksums where the
mirror serves intact files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
FETCH = REPO_ROOT / "scripts" / "fetch-cmapss.sh"


def download(*, subset_all: bool = False) -> None:
    cmd = [str(FETCH)] + (["--subset-all"] if subset_all else [])
    subprocess.run(cmd, check=True)


__all__ = ["download"]
