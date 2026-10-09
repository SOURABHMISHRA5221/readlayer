"""Env-driven settings. Every tunable lives here; nothing reads os.environ directly."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
    # Faithfulness judge (task `verify`). Empty = MODEL_QUALITY; set to compare judges (M5).
    model_judge: str = ""
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

    # Recommendations (M6.5). Keys stay server-side; SecretStr keeps them out of reprs and logs.
    tavily_api_key: SecretStr = SecretStr("")
    youtube_api_key: SecretStr = SecretStr("")
    search_daily_cap: int = 300  # outgoing search calls per UTC day, all providers
    youtube_search_daily_cap: int = 90  # YouTube's search.list has its own 100/day bucket
    search_timeout_s: float = 10.0
    recs_cache_ttl_h: float = 48.0
    # New URLs a reader may ingest per UTC day (CLAUDE.md cost guardrails). Anonymous (demo)
    # readers get a smaller cap, plus a shared cap across all anonymous readers so minting
    # fresh anonymous accounts can't multiply it.
    ingest_daily_cap: int = 20
    anon_ingest_daily_cap: int = 3
    anon_global_ingest_daily_cap: int = 30
    # Uncached web searches triggered by anonymous readers, all of them together, per UTC day.
    anon_search_daily_cap: int = 100

    # Explanations (M5): uncached generations per reader per UTC day, and for all anonymous
    # readers together. Past a cap the card shows the definition only; cached ones stay free.
    explain_daily_cap: int = 100
    anon_explain_daily_cap: int = 40
    anon_global_explain_daily_cap: int = 400

    # Per-uid request limits per minute (DESIGN §11.5), in memory per instance.
    rate_general_per_min: int = 120
    rate_general_anon_per_min: int = 60
    rate_annotations_per_min: int = 60
    rate_annotations_anon_per_min: int = 30
    rate_events_per_min: int = 30
    rate_explain_per_min: int = 60
    rate_explain_anon_per_min: int = 30

    # Firebase Auth project for ID-token verification; defaults to gcp_project.
    firebase_project: str = ""
    # Browser origins allowed by CORS, comma-separated (the Hosting origins in prod).
    cors_origins: str = ""

    # Local dev only, for curl and scripts: a request with no Authorization header acts as a
    # fixed dev uid. Refused at startup on Cloud Run or with ENV=prod, and re-checked per request.
    dev_auth_bypass: bool = False
    # Cloud Run sets K_SERVICE on every revision; its presence means we are not on a laptop.
    k_service: str = ""

    @model_validator(mode="after")
    def _no_auth_bypass_when_deployed(self) -> "Settings":
        if self.dev_auth_bypass and (self.k_service or self.env == "prod"):
            raise ValueError("DEV_AUTH_BYPASS must never be set on Cloud Run or with ENV=prod")
        return self

    @property
    def bypass_allowed(self) -> bool:
        return self.dev_auth_bypass and self.env == "dev" and not self.k_service

    @property
    def judge_model(self) -> str:
        return self.model_judge or self.model_quality

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def auth_project(self) -> str:
        return self.firebase_project or self.gcp_project


@lru_cache
def get_settings() -> Settings:
    return Settings()
