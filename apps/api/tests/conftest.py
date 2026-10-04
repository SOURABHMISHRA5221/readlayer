import pytest
from tenacity import wait_none

from app import llm
from app.config import Settings
from app.store.spend_repo import InMemorySpendStore


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        gcp_project="test-project",
        model_fast="vertex_ai/fast",
        model_quality="vertex_ai/quality",
        model_fallback="vertex_ai/fallback",
        llm_daily_budget_usd=1.0,
        uid_hash_salt="test-salt",
    )


@pytest.fixture
def spend(monkeypatch: pytest.MonkeyPatch) -> InMemorySpendStore:
    store = InMemorySpendStore()
    monkeypatch.setattr(llm, "retry_wait", wait_none())
    llm.set_spend_store(store)
    yield store
    llm.set_spend_store(None)
