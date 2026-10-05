"""Fleet Digital Twin backend package.

Threading discipline lives here — and only here — because it must run before
any numeric library is imported, anywhere in the process.

Importing xgboost + numpy costs ~290 MB RSS on its own, and the BLAS/OpenMP
runtimes size their thread pools from the *host* CPU count. On a 0.1-CPU
free-tier instance that spawns a dozen threads per predict that all serialize
on a tenth of a core while each holds buffers: slower predictions *and* more
RSS, which is exactly how a second device downloading the scene mid-tick tips
the process into an OOM restart (served by the proxy as 502/503).

Single-threaded math is both leaner and faster on fractional CPUs. These are
defaults, not mandates: an explicit operator setting is always honoured.

This cannot live in render.yaml alone — dashboard-created services never see
blueprint env vars, so the one deployment that needed it most never got it.
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
# glibc carves a malloc arena per thread and never fully returns them; with the
# replay + request threadpool churning, retained arenas are dead RSS that only
# grows. Two arenas is plenty for a single worker.
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
