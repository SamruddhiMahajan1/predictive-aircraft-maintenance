"""Config-driven training (docs/16 §10.3). TOML via stdlib tomllib, validated strictly.

Unknown keys fail hard — `max_depth = "6"` or a typo'd key is an error, never a
silent default. Hyperparameters stop being literals buried in notebook cells.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"

_KNOWN_TOP = {"name", "datasets", "rul_cap", "seed", "split", "features", "model", "gates"}
_KNOWN_SPLIT = {"strategy", "test_size", "groups"}
_KNOWN_FEATURES = {"rolling_window", "rolling_ddof", "zscore_by", "excluded"}
_KNOWN_MODEL = {
    "n_estimators",
    "learning_rate",
    "max_depth",
    "min_child_weight",
    "subsample",
    "colsample_bytree",
    "reg_lambda",
    "early_stopping_rounds",
}
_KNOWN_GATES = {"max_cv_rmse", "max_test_rmse", "max_mae", "min_r2"}


@dataclass(frozen=True)
class SplitConfig:
    strategy: str = "group_shuffle"
    test_size: float = 0.20
    groups: str = "unit"


@dataclass(frozen=True)
class FeaturesConfig:
    rolling_window: int = 5
    rolling_ddof: int = 0
    zscore_by: str = "regime"
    excluded: tuple = ("unit", "cycle", "RUL")


@dataclass(frozen=True)
class ModelConfig:
    n_estimators: int = 1000
    learning_rate: float = 0.05
    max_depth: int = 6
    min_child_weight: int = 3
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_lambda: float = 1.0
    early_stopping_rounds: int = 50


@dataclass(frozen=True)
class GatesConfig:
    max_cv_rmse: float = 21.0
    max_test_rmse: float = 25.0
    max_mae: float = 20.0
    min_r2: float = 0.80


@dataclass(frozen=True)
class TrainConfig:
    name: str
    datasets: tuple
    rul_cap: int = 125
    seed: int = 42
    split: SplitConfig = field(default_factory=SplitConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    gates: GatesConfig = field(default_factory=GatesConfig)

    def resolved_dict(self) -> dict:
        return {
            "name": self.name,
            "datasets": list(self.datasets),
            "rul_cap": self.rul_cap,
            "seed": self.seed,
            "split": self.split.__dict__,
            "features": {**self.features.__dict__, "excluded": list(self.features.excluded)},
            "model": self.model.__dict__,
            "gates": self.gates.__dict__,
        }


def _reject_unknown(mapping: dict, known: set, where: str) -> None:
    unknown = set(mapping) - known
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")


def load_config(path: str | Path) -> TrainConfig:
    p = Path(path)
    if not p.is_absolute():
        cand = CONFIG_DIR / p.name if p.suffix else CONFIG_DIR / f"{p}.toml"
        p = cand if cand.exists() and not p.exists() else p
    raw = tomllib.loads(p.read_text())
    _reject_unknown(raw, _KNOWN_TOP, str(p))
    split = raw.get("split", {})
    feats = raw.get("features", {})
    model = raw.get("model", {})
    gates = raw.get("gates", {})
    _reject_unknown(split, _KNOWN_SPLIT, "split")
    _reject_unknown(feats, _KNOWN_FEATURES, "features")
    _reject_unknown(model, _KNOWN_MODEL, "model")
    _reject_unknown(gates, _KNOWN_GATES, "gates")
    return TrainConfig(
        name=raw.get("name", p.stem),
        datasets=tuple(raw.get("datasets", ["FD001"])),
        rul_cap=int(raw.get("rul_cap", 125)),
        seed=int(raw.get("seed", 42)),
        split=SplitConfig(**{k: split[k] for k in _KNOWN_SPLIT if k in split}),
        features=FeaturesConfig(
            **{
                k: (tuple(feats[k]) if k == "excluded" else feats[k])
                for k in _KNOWN_FEATURES
                if k in feats
            }
        ),
        model=ModelConfig(**{k: model[k] for k in _KNOWN_MODEL if k in model}),
        gates=GatesConfig(**{k: gates[k] for k in _KNOWN_GATES if k in gates}),
    )


__all__ = ["TrainConfig", "load_config", "CONFIG_DIR"]
