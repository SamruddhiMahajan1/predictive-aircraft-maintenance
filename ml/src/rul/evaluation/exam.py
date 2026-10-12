"""Exam-style CV: rebuild features on truncated histories (notebook, kept verbatim).

A cycle may only use data available at that cycle — no future leakage. See
modeling/_fit.py _rows_to_windows: every prefix of an engine's history is a
training window.
"""

from __future__ import annotations

__all__ = []
