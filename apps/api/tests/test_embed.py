from types import SimpleNamespace

import litellm
import pytest

from app import llm
from app.store.spend_repo import InMemorySpendStore


class FakeEmbedder:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []
        monkeypatch.setattr(litellm, "aembedding", self.aembedding)
        monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0001)

    async def aembedding(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            data=[{"embedding": [3.0, 4.0]} for _ in kwargs["input"]],
            usage=SimpleNamespace(prompt_tokens=7),
        )


@pytest.fixture
def embed_settings(settings):
    return settings.model_copy(update={"model_embed": "vertex_ai/embed", "embed_dim": 2})


async def test_embed_normalises_and_records_spend(monkeypatch, embed_settings, spend):
    fake = FakeEmbedder(monkeypatch, ["ok"])
    result = await llm.embed(["a", "b"], task_type="RETRIEVAL_QUERY", settings=embed_settings)
    assert result.vectors == [[0.6, 0.8], [0.6, 0.8]]
    assert result.cost_usd == pytest.approx(0.0001) and result.tokens == 7
    assert spend.calls == 1
    call = fake.calls[0]
    assert call["dimensions"] == 2 and call["task_type"] == "RETRIEVAL_QUERY"
    assert call["vertex_project"] == "test-project"


async def test_embed_batches_large_inputs(monkeypatch, embed_settings, spend):
    fake = FakeEmbedder(monkeypatch, ["ok", "ok", "ok"])
    texts = [str(i) for i in range(llm.EMBED_BATCH * 2 + 1)]
    result = await llm.embed(texts, task_type="SEMANTIC_SIMILARITY", settings=embed_settings)
    assert len(result.vectors) == len(texts)
    assert [len(c["input"]) for c in fake.calls] == [llm.EMBED_BATCH, llm.EMBED_BATCH, 1]


async def test_embed_refuses_past_budget(monkeypatch, embed_settings):
    fake = FakeEmbedder(monkeypatch, ["ok"])
    llm.set_spend_store(InMemorySpendStore(initial_usd=1.0))
    try:
        with pytest.raises(llm.BudgetExceeded):
            await llm.embed(["a"], task_type="RETRIEVAL_QUERY", settings=embed_settings)
    finally:
        llm.set_spend_store(None)
    assert fake.calls == []


async def test_embed_retries_then_unavailable_without_fallback(monkeypatch, embed_settings, spend):
    err = litellm.RateLimitError("slow", llm_provider="vertex_ai", model="x")
    fake = FakeEmbedder(monkeypatch, [err, err, err])
    with pytest.raises(llm.LLMUnavailable):
        await llm.embed(["a"], task_type="RETRIEVAL_QUERY", settings=embed_settings)
    assert len(fake.calls) == embed_settings.llm_max_retries + 1
    assert {c["model"] for c in fake.calls} == {"vertex_ai/embed"}


async def test_embed_client_error_rejected(monkeypatch, embed_settings, spend):
    err = litellm.BadRequestError("bad", llm_provider="vertex_ai", model="x")
    FakeEmbedder(monkeypatch, [err])
    with pytest.raises(llm.LLMRejected):
        await llm.embed(["a"], task_type="RETRIEVAL_QUERY", settings=embed_settings)


async def test_embed_requires_model(settings, spend):
    with pytest.raises(llm.LLMUnavailable):
        await llm.embed(["a"], task_type="RETRIEVAL_QUERY", settings=settings)
