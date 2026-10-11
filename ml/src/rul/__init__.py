"""rul -- the canonical home for the remaining-life model and its feature contract.

Two audiences, deliberately separated:

    rul.contract   pure standard library, no third-party imports. Imported by BOTH the
                   training pipeline and the serving path, so the transform cannot drift
                   between them. This is what the backend depends on.

    everything else in this package (training, evaluation, registry) is built on top and
                   is NOT imported by the backend. Importing `rul.contract` must keep
                   working when numpy, xgboost, scikit-learn and matplotlib are all
                   absent -- which is why this module imports nothing eagerly.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]