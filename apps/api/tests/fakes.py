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
PASS = {
    "claims": [{"claim": "c", "verdict": "entailed", "reason": "r"}],
    "background_issue": "none",
}
FAIL = {
    "claims": [{"claim": "c", "verdict": "not_entailed", "reason": "not stated"}],
    "background_issue": "none",
}


class ExplainLLM:
    """Replaces llm.run_with_meta for explain/verify. Each task pops its next scripted item
    (the last one repeats); an Exception item is raised."""

    def __init__(self, drafts=None, verdicts=None) -> None:
        self.drafts = list(drafts or [GOOD_DRAFT])
        self.verdicts = list(verdicts or [PASS])
        self.calls: list[dict[str, Any]] = []

    def tasks(self) -> list[str]:
        return [c["task"] for c in self.calls]

    async def __call__(self, task, schema, prompt_vars, **_):
        self.calls.append({"task": task, "vars": prompt_vars})
        queue = self.drafts if task == "explain" else self.verdicts
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        model = "vertex_ai/quality"
        return llm.LLMResult(schema.model_validate(item), meta(model, 0.001, task))


from tests.fake_auth import FakeAuthAdmin, auth, token  # noqa: E402,F401  (re-export)
