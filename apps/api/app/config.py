"""Env-driven settings. Every tunable lives here; nothing reads os.environ directly."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"

    gcp_project: str = ""
    vertex_location: str = "global"

    # Model ids are LiteLLM strings (e.g. "vertex_ai/gemini-3.8-flash"); never hard-coded in code.
    model_fast: str = ""
    model_quality: str = ""
    model_fallback: str = ""
    # Embeddings have no fallback: vectors from another model aren't comparable.
    model_embed: str = ""
    embed_dim: int = 256

    # Concept graph (DESIGN §2): gs:// URI or local path. Empty = no graph (dev and tests).
    concepts_uri: str = ""
    link_threshold: float = 0.80  # calibrated by scripts/build_concepts.py
    dedupe_threshold: float = 0.88

    llm_daily_budget_usd: float = 8.0
    llm_timeout_s: float = 20.0
    llm_max_retries: int = 2
    # Per-token (input, output) USD prices for models missing from LiteLLM's price map.
    model_price_overrides: dict[str, tuple[float, float]] = Field(default_factory=dict)

    uid_hash_salt: str = ""

    # Local dev only: every request is the fixed dev uid, no token check. Set by `make dev`.
    dev_auth_bypass: bool = False
    # Cloud Run sets K_SERVICE on every revision; its presence means we are not on a laptop.
    k_service: str = ""

    @model_validator(mode="after")
    def _no_auth_bypass_when_deployed(self) -> "Settings":
        if self.dev_auth_bypass and (self.k_service or self.env == "prod"):
            raise ValueError("DEV_AUTH_BYPASS must never be set on Cloud Run or with ENV=prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
