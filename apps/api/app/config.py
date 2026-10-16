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
    # Landing illustrations (decision 44): a Gemini image model; no fallback. The price per image
    # is charged whenever LiteLLM can't price the response, so the budget guard never sees 0.
    model_image: str = ""
    model_image_price_usd: float = 0.0672

    # Concept graph (DESIGN §2): gs:// URI or local path. Empty = no graph (dev and tests).
    concepts_uri: str = ""
    link_threshold: float = 0.80  # calibrated by scripts/build_concepts.py
    dedupe_threshold: float = 0.88
    # Phase 2 of an ingest (demand extraction + linking) is cut off after this; its lease on the
    # pending doc lasts 30 s longer, so an expired lease always means the run has stopped.
    analyse_timeout_s: float = 120.0
    # Online concept growth (M2.2, DESIGN §2): new concepts from an ingest's unlinked demands.
    # Off until the seeded graph is serving (deploy.env.yaml); also the demo kill switch.
    growth_enabled: bool = False
    growth_per_article: int = 5
    growth_per_uid_day: int = 25  # per reader, Google or anonymous (decision 35)
    growth_per_day: int = 100  # all readers together
    anon_growth_daily_cap: int = 150  # all anonymous readers together (M9 G6: 30 URLs × 5)
    growth_refresh_s: float = 60.0  # how often an instance looks for concepts grown elsewhere
    # Inside phase 2, bounded by the time phase 2 has left (minus 5 s). 30 s, not the plan's 20 s:
    # a harness ingest needed 20.0 s for 4 concepts (five batched calls incl. MODEL_QUALITY).
    growth_timeout_s: float = 30.0
    # Profile edits by prompt per UTC day (DESIGN §15.3, §11.5): per reader, and for demo readers
    # per uid plus a cap shared across all anonymous readers.
    profile_edit_daily_cap: int = 10
    anon_profile_edit_daily_cap: int = 3
    anon_global_profile_edit_daily_cap: int = 30

    llm_daily_budget_usd: float = 8.0
    llm_timeout_s: float = 20.0
    llm_max_retries: int = 2
    # Decision 67 L1: Gemini 3 thinking level per task (task -> low/medium/high), over the
    # route's own; checked against llm.ROUTES at startup (llm.check_effort_overrides).
    llm_reasoning_effort: dict[str, Literal["low", "medium", "high"]] = Field(default_factory=dict)
    # Per-token (input, output) USD prices for models missing from LiteLLM's price map.
    model_price_overrides: dict[str, tuple[float, float]] = Field(default_factory=dict)
    # Per-token USD price of audio input, for models whose LiteLLM entry has none (LiteLLM 1.104
    # has none for Gemini 3.x). A media call on a model with no audio price is refused, so an
    # unpriced recording can never reach the ledger as cheap (Media plan R6).
    model_audio_price_overrides: dict[str, float] = Field(default_factory=dict)

    # Media: YouTube videos and podcast episodes read as transcripts (decision 54, DESIGN §21).
    media_enabled: bool = True  # kill switch: false → media URLs answer "Open original"
    media_audio_enabled: bool = True  # podcasts only (plan R12)
    media_video_enabled: bool = True  # YouTube only; on: whole videos ≤ 10 min answer (step 7)
    # 10 minutes for videos, 12 for podcasts (Sourabh, 2026-10-14: media is minor support; short
    # clips are enough; podcasts raised to 12 because Apple's length leaves out stitched-in ads).
    # A video is one call; an episode one window up to 11 min, two (sequential) up to 12; a
    # small file, memory well inside 1 GiB.
    media_max_video_s: int = 600
    media_max_audio_s: int = 720
    media_max_audio_bytes: int = 24_000_000  # 12 min at 256 kbps is 23 MB
    # Audio windows in flight after window 1; each holds ~3 × 20 MB of base64 and JSON (5R10).
    # 2, not 4: T02's harness run peaked at 686 MB (idle API 277 MB) with two in flight.
    media_audio_parallel_windows: int = Field(default=2, ge=1)
    # New recordings per UTC day: per signed-in reader, per demo reader, all demo readers.
    media_daily_cap: int = 5
    anon_media_daily_cap: int = 1
    anon_global_media_daily_cap: int = 10
    # videos.list, Apple lookups and audio pre-checks per UTC day, everyone together (R5).
    media_lookup_daily_cap: int = 300
    # Media spend per UTC day inside LLM_DAILY_BUDGET_USD (Sourabh: "mark 3 dollar budget", R7).
    media_daily_budget_usd: float = 3.0
    # Expected transcribe cost per minute of recording, at the cautious audio price (R6): drives
    # the budget pre-check, the per-item ceiling (2×) and a timed-out window's ledger charge.
    media_est_usd_per_min: float = 0.006

    uid_hash_salt: str = ""

    # Recommendations (M6.5). Keys stay server-side; SecretStr keeps them out of reprs and logs.
    tavily_api_key: SecretStr = SecretStr("")
    youtube_api_key: SecretStr = SecretStr("")
    search_daily_cap: int = 300  # outgoing search calls per UTC day, all providers
    # For you feed (M7.5): its own share of those calls, so it can never starve Up next.
    feed_search_daily_cap: int = 60
    # End-of-article story search (decision 69 B2): corpus articles only, ≤ 2 searches per article
    # ever (article + video), its own share so judges opening articles can't starve the feed.
    story_search_daily_cap: int = 40
    # Outlet collection job (decision 50): POST /v1/internal/feeds/collect accepts only a Google
    # ID token for this service account with this audience. Either one empty → always 403.
    feed_job_sa_email: str = ""
    feed_job_audience: str = ""
    # Learning goals resolved per reader per UTC day (≤ 1 embed + 1 link_confirm each; M7.5).
    goal_resolve_daily_cap: int = 10
    # Onboarding (decisions 41, 42): free-text resolves and discover calls that start new
    # searches, per reader per UTC day; concept searches shared by everyone (within the feed
    # cap); the topic fallback's cosine floor, set from evals/cases/onboarding_topics.yaml
    # (2026-10-11: 0.86 → precision 9/9, recall 9/22, the 5 "none" phrases stay unmatched;
    # with the 109-entry alias list first: 10/22, 0 wrong; 8/20 without the 2 copied phrases).
    onboarding_resolve_daily_cap: int = 5
    onboarding_discover_daily_cap: int = 3
    onboarding_concept_search_daily_cap: int = 20
    onboarding_topic_threshold: float = 0.86
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
    # Firestore project; defaults to gcp_project. The emulator harness sets it to its demo
    # project while Vertex AI and Cloud Storage keep using gcp_project.
    firestore_project: str = ""
    # Browser origins allowed by CORS, comma-separated (the Hosting origins in prod).
    cors_origins: str = ""

    # Local dev only, for curl and scripts: a request with no Authorization header acts as a
    # fixed dev uid. Refused at startup on Cloud Run or with ENV=prod, and re-checked per request.
    dev_auth_bypass: bool = False
    # Cloud Run sets K_SERVICE on every revision; its presence means we are not on a laptop.
    k_service: str = ""

    # Local emulator harness only (M7 `make dev-emulator`). With the Auth emulator host set,
    # firebase-admin accepts unsigned emulator tokens, so these are refused on Cloud Run too.
    firebase_auth_emulator_host: str = ""
    firestore_emulator_host: str = ""

    @model_validator(mode="after")
    def _no_auth_bypass_when_deployed(self) -> "Settings":
        deployed = bool(self.k_service) or self.env == "prod"
        if self.dev_auth_bypass and deployed:
            raise ValueError("DEV_AUTH_BYPASS must never be set on Cloud Run or with ENV=prod")
        if deployed and (self.firebase_auth_emulator_host or self.firestore_emulator_host):
            raise ValueError("emulator hosts must never be set on Cloud Run or with ENV=prod")
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

    @property
    def db_project(self) -> str:
        return self.firestore_project or self.gcp_project


@lru_cache
def get_settings() -> Settings:
    return Settings()
