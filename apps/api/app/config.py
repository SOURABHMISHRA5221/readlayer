"""Env-driven settings. Every tunable lives here; nothing reads os.environ directly."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    llm_daily_budget_usd: float = 8.0
    llm_timeout_s: float = 20.0
    llm_max_retries: int = 2
    # Per-token (input, output) USD prices for models missing from LiteLLM's price map.
    model_price_overrides: dict[str, tuple[float, float]] = Field(default_factory=dict)

    uid_hash_salt: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
