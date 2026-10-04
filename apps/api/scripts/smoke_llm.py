"""Call llm.run once against real Vertex + Firestore and print tokens and cost.

uv run python -m scripts.smoke_llm
uv run python -m scripts.smoke_llm --model-override vertex_ai/does-not-exist   # test fallback
"""

import argparse
import asyncio
import json

from pydantic import BaseModel, Field

from app import llm
from app.config import get_settings
from app.log import configure_logging

SAMPLE = (
    "The central bank held the repo rate at 6.5% on Friday. "
    "Officials said inflation may ease later in the year."
)


class SmokeOut(BaseModel):
    topic: str = Field(max_length=80)
    sentence_count: int = Field(ge=0)


async def main(model_override: str | None) -> None:
    settings = get_settings()
    if model_override:
        settings = settings.model_copy(update={"model_fast": model_override})
    result = await llm.run_with_meta("smoke", SmokeOut, {"text": SAMPLE}, settings=settings)
    meta = result.meta
    print(f"output       {result.output.model_dump_json()}")
    print(f"model        {meta.model}  (fell back: {meta.fell_back}, attempts: {meta.attempts})")
    print(f"prompt       smoke {meta.prompt_version}")
    print(f"tokens       in={meta.tokens_in} out={meta.tokens_out}")
    print(f"cost_usd     {meta.cost_usd:.6f}")
    print(f"latency_ms   {meta.latency_ms}")
    print(f"spent today  ${await llm.get_spend_store().get_today():.6f}")
    print(json.dumps({"schema_valid": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-override", help="replace MODEL_FAST, e.g. a bad id")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    asyncio.run(main(args.model_override))
