"""Shared fakes: a scripted demand extractor and a scripted explain/verify pair in place of
the LLM."""

from typing import Any

from app import llm
from app.ingest.demands import DemandExtraction


def meta(
    model: str = "vertex_ai/fast", cost: float = 0.0004, task: str = "extract_demands"
) -> llm.CallMeta:
    return llm.CallMeta(
        task=task,
        model=model,
        prompt_version="extract_demands-v1",
        tokens_in=1200,
        tokens_out=300,
        cost_usd=cost,
        latency_ms=5.0,
        fell_back=False,
        attempts=1,
    )


class FakeLLM:
    """Replaces llm.run_with_meta. `reply(prompt_vars)` builds the output dict per call."""

    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.reply = reply or (lambda _vars: {"paragraphs": []})
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, task, schema, prompt_vars, **_):
        self.calls.append({"task": task, "vars": prompt_vars})
        if self.error:
            raise self.error
        output = DemandExtraction.model_validate(self.reply(prompt_vars))
        return llm.LLMResult(output, meta())


GOOD_DRAFT = {
    "background": "A yield curve plots interest rates across loan lengths.",
    "author_says": "Analysts said the curve may invert.",
    "analogy_domain": None,
}
GOOD_RESTATEMENT = {"author_says": GOOD_DRAFT["author_says"]}
GOOD_BACKGROUND = {"background": GOOD_DRAFT["background"], "analogy_domain": None}
PASS = {"claims": [{"claim": "c", "verdict": "entailed", "reason": "r"}]}
FAIL = {"claims": [{"claim": "c", "verdict": "not_entailed", "reason": "not stated"}]}
BG_PASS = {"background_issue": "none"}
BG_FAIL = {"background_issue": "article_claim", "background_reason": "names this article's bank"}


class ExplainLLM:
    """Replaces llm.run_with_meta for the four explanation tasks. Each task pops its next
    scripted item (the last one repeats); an Exception item is raised."""

    def __init__(self, restatements=None, backgrounds=None, verdicts=None, bg_verdicts=None):
        self.queues: dict[str, list] = {
            "restate": list(restatements or [GOOD_RESTATEMENT]),
            "explain": list(backgrounds or [GOOD_BACKGROUND]),
            "verify": list(verdicts or [PASS]),
            "verify_background": list(bg_verdicts or [BG_PASS]),
        }
        self.calls: list[dict[str, Any]] = []

    def script(self, task: str, items: list) -> None:
        self.queues[task] = list(items)

    def tasks(self) -> list[str]:
        return [c["task"] for c in self.calls]

    def count(self, task: str) -> int:
        return sum(c["task"] == task for c in self.calls)

    async def __call__(self, task, schema, prompt_vars, **_):
        self.calls.append({"task": task, "vars": prompt_vars})
        queue = self.queues[task]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        model = "vertex_ai/quality"
        return llm.LLMResult(schema.model_validate(item), meta(model, 0.001, task))


def pending_doc(url: str, source: str = "user_ingested", texts: list[str] | None = None):
    """A phase-1 article as fetch_and_extract would store it."""
    from datetime import UTC, datetime

    from app.ingest.models import PendingDoc, PendingParagraph
    from app.ingest.urls import url_hash
    from app.store.pending_repo import PENDING_TTL

    now = datetime.now(UTC)
    paragraphs = texts or ["Opened article text about bond yields and the curve."]
    return PendingDoc(
        content_id=url_hash(url),
        url=url,
        final_url=url,
        title="Opened",
        site="explainer.example",
        source=source,
        fetched_at=now.isoformat(),
        paragraphs=[PendingParagraph(id=f"p{i}", text=t) for i, t in enumerate(paragraphs)],
        expire_at=now + PENDING_TTL,
    )


def fake_fetch_and_extract(sources: list[str] | None = None):
    """Replaces the router's fetch_and_extract: stores a pending doc, no network, no LLM."""

    async def fetch_and_extract(url, source="fetch", grow_slots=0):
        from app.store.pending_repo import get_pending_repo

        if sources is not None:
            sources.append(source)
        return await get_pending_repo().create(pending_doc(url, source))

    return fetch_and_extract


def consented(client):
    """A signed-in reader who accepted the consent screen (M7): records allowed from now on."""
    assert client.post("/v1/me/consent", json={"version": "consent-v1"}).status_code == 200
    return client


from tests.fake_auth import FakeAuthAdmin, auth, token  # noqa: E402,F401  (re-export)


def onboard(uid: str) -> None:
    """A signed-in reader who has consented and finished onboarding (M8's extension gate)."""
    import asyncio

    from app.store.docstore import get_doc_store

    async def seed(t):
        t.set(f"users/{uid}", {"consent": {"version": "consent-v1"}, "onboarding_done": True})

    asyncio.run(get_doc_store().run(seed))
