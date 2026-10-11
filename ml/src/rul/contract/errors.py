"""The one exception type this package raises on its own account.

Deliberately NOT the backend's ``BusinessRuleError``. The contract sits below the API and
must not import anything from it: ``rul.contract`` is pure standard library, and the
dependency runs backend -> ml, never the other way. Mapping a contract failure onto an
HTTP status is the caller's job, and the backend does that in ``app/ml/inference.py``.
"""

from __future__ import annotations


class ContractError(Exception):
    """A feature matrix could not be built to the contract the booster was trained on.

    Raised, never returned as ``None``, because every way this package can fail is a way
    a caller could otherwise paper over: serving raw sensors to a booster trained on
    z-scores does not crash, it predicts confidently from the wrong scale.
    """


__all__ = ["ContractError"]