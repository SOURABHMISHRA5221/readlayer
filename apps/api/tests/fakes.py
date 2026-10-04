"""Shared fakes for ingestion tests: a scripted demand extractor in place of the LLM."""

from typing import Any

from app import llm
from app.ingest.demands import DemandExtraction


def meta(model: str = "vertex_ai/fast", cost: float = 0.0004) -> llm.CallMeta:
    return llm.CallMeta(
        task="extract_demands",
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
