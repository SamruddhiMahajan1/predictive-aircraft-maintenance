"""Application settings. Every env var is prefixed FDT_ (docs/02 §6.1)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Committed placeholder. `docker compose` makes the real value mandatory and
# `_reject_insecure_production` refuses to start with it in production.
DEV_JWT_SECRET = "dev-only-insecure-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FDT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Fleet Digital Twin API"
    # "development" | "staging" | "production"
    environment: str = "development"
    log_level: str = "INFO"

    # storage
    database_url: str = "postgresql+psycopg://fdt:fdt@localhost:5432/fdt"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # auth
    # The default is a development placeholder and the app refuses to boot on it
    # outside development — see `_validate` below. Never ship a real secret here.
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 720

    # http
    # NoDecode: a comma-separated env string must not be JSON-parsed first
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # demo / realtime
    demo_mode: bool = True
    demo_tick_seconds: float = 1.2
    ws_queue_size: int = 256

    # domain
    rul_cap: int = 125

    # ml — artifacts as produced by Model_training_249.ipynb (docs/08 §4).
    # ml_variant selects which model generation to serve:
    #   "holdout"  the 80/20 model, StandardScaler preprocessing (Phase 1)
    #   "full"     the all-engines refit, per-regime z-score preprocessing (Phase 2)
    ml_variant: str = "full"
    ml_dataset: str = "FD001"
    # None  -> derive the filename from ml_variant (the normal case)
    # ""    -> explicitly no such artifact (e.g. the z-score variant ships no scaler)
    ml_model_path: str | None = None
    ml_contract_path: str | None = None
    ml_scaler_path: str | None = None
    ml_stats_path: str | None = None
    ml_fallback: bool = True
    ml_window: int = 30
    s6_median_fd001: float = 21.6098

    # paths
    # Resolved relative to the process CWD; the container sets WORKDIR /app and the
    # Dockerfile asserts the directory exists, so a misconfigured mount fails the
    # build instead of silently degrading the replay engine to an empty dataset.
    data_dir: Path = Path("data")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _reject_insecure_production(self) -> Settings:
        """Refuse to serve real traffic signed with the committed dev secret.

        A default that silently works in production is how a demo repo turns into a
        token-forging incident. `docker compose` already makes FDT_JWT_SECRET mandatory;
        this closes the same hole for a bare `uvicorn`/`make run`.
        """
        if self.environment == "production":
            if self.jwt_secret == DEV_JWT_SECRET:
                raise ValueError(
                    "FDT_JWT_SECRET still holds the development placeholder while "
                    "FDT_ENVIRONMENT=production. Generate one with "
                    "`openssl rand -hex 32`."
                )
            if self.demo_mode:
                raise ValueError(
                    "FDT_DEMO_MODE must be false when FDT_ENVIRONMENT=production."
                )
        return self

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def ml_dir(self) -> Path:
        return self.data_dir / "ml" / self.ml_variant

    # Filenames differ per generation. Both are resolved from ml_dir unless the
    # operator overrides them explicitly.
    # ClassVar: this is a lookup table, not a field. Without it pydantic turns the
    # dict into a private attribute, so `Settings._ML_FILES` stops being iterable
    # and anything deriving a variant list from it breaks at import.
    _ML_FILES: ClassVar[dict[str, tuple[str, str, str, str]]] = {
        # The contract for this variant names its own baselines file
        # (regime_baselines_fd001.json), so no default is guessed here.
        "full": ("xgboost_fd001_full.json", "feature_contract_fd001_full.json",
                 "", ""),
        "holdout": ("xgboost_fd001_rul.json", "feature_contract.json",
                    "scaler_fd001.pkl", "baseline_stats.json"),
        # The pooled candidate: trained on FD001+FD002+FD003+FD004, 30 features
        # (the 29 plus regime_global), z-scored against four subsets of baselines. Its
        # contract names its own baselines file, so none is guessed here.
        "all": ("xgboost_all_full.json", "feature_contract_all_full.json", "", ""),
    }

    def _ml_file(self, index: int, override: str | None) -> str:
        # `None` means "derive from the variant"; an explicit "" means "not supplied",
        # which is different and must be honoured — otherwise a variant whose default
        # is a real file can never be configured to run without it.
        if override is not None:
            return override
        try:
            names = self._ML_FILES[self.ml_variant]
        except KeyError as exc:  # pragma: no cover - guarded by the validator below
            raise ValueError(
                f"unknown ml_variant {self.ml_variant!r}; "
                f"expected one of {sorted(self._ML_FILES)}"
            ) from exc
        name = names[index]
        return str(self.ml_dir / name) if name else ""

    @property
    def ml_model_path_resolved(self) -> str:
        return self._ml_file(0, self.ml_model_path)

    @property
    def ml_contract_path_resolved(self) -> str:
        return self._ml_file(1, self.ml_contract_path)

    @property
    def ml_scaler_path_resolved(self) -> str:
        return self._ml_file(2, self.ml_scaler_path)

    @property
    def ml_stats_path_resolved(self) -> str:
        """Baselines: per-regime for the z-score variant, single regime otherwise."""
        return self._ml_file(3, self.ml_stats_path)

    @property
    def cmapss_dir(self) -> Path:
        return self.data_dir / "cmapss"

    def cmapss_file(self, subset: str, kind: str) -> Path:
        """Path of one raw C-MAPSS file: kind is train | test | RUL."""
        return self.cmapss_dir / f"{kind}_{subset}.txt"

    @property
    def replay_subset(self) -> str:
        """Subset the demo replays. Not the same thing as the model's training breadth.

        A model may be trained on FD001+FD002+FD003+FD004 while every aircraft still
        binds 1:1 to an FD001 engine, so this stays the single subset the fleet reads.
        It is what the baselines are looked up under and what regime ids are assigned in.
        """
        return self.ml_dataset


@lru_cache
def get_settings() -> Settings:
    return Settings()