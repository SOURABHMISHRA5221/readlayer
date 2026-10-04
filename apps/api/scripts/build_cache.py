"""On-disk cache for the concept build, so a crash or rerun doesn't pay for the same calls twice.

LLM outputs are keyed by (task, prompt version, prompt vars); embeddings by (model, dim, task
type, text). Cached LLM entries keep their original cost so the report can show the full build
cost, not just this run's.
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app import llm
from app.config import Settings


def _key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class _JsonlStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.data[row["k"]] = row["v"]

    def put(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"k": key, "v": value}) + "\n")


class BuildCache:
    def __init__(self, root: Path, settings: Settings) -> None:
        self.settings = settings
        self._llm = _JsonlStore(root / "llm.jsonl")
        self._emb = _JsonlStore(root / "embed.jsonl")
        self._wiki = _JsonlStore(root / "wikipedia.jsonl")
        self.llm_cost_new = 0.0
        self.llm_cost_cached = 0.0
        self.embed_cost_new = 0.0

    # ---------------------------------------------------------------- LLM

    @staticmethod
    def _llm_key(task: str, prompt_vars: dict[str, Any]) -> str:
        version = llm.load_prompt(task).version
        return _key(task, version, json.dumps(prompt_vars, sort_keys=True))

    def has(self, task: str, prompt_vars: dict[str, Any]) -> bool:
        """True when this exact call is cached with a non-fallback answer (it will cost $0)."""
        hit = self._llm.data.get(self._llm_key(task, prompt_vars))
        return hit is not None and not hit["meta"]["fell_back"]

    def cost_per_call(self, task: str) -> float:
        """Mean cost of cached, non-fallback calls for `task` (0.0 if none are cached)."""
        costs = [
            v["meta"]["cost_usd"]
            for v in self._llm.data.values()
            if v["meta"]["task"] == task and not v["meta"]["fell_back"]
        ]
        return sum(costs) / len(costs) if costs else 0.0

    async def run(
        self, task: str, schema: type[BaseModel], prompt_vars: dict[str, Any]
    ) -> llm.LLMResult[Any]:
        key = self._llm_key(task, prompt_vars)
        hit = self._llm.data.get(key)
        if hit is not None and not hit["meta"]["fell_back"]:  # a fallback answer is re-asked
            meta = llm.CallMeta(**hit["meta"])
            self.llm_cost_cached += meta.cost_usd
            return llm.LLMResult(schema.model_validate(hit["output"]), meta)
        result = await llm.run_with_meta(task, schema, prompt_vars)
        self.llm_cost_new += result.meta.cost_usd
        self._llm.put(key, {"output": result.output.model_dump(), "meta": asdict(result.meta)})
        return result

    # ---------------------------------------------------------------- embeddings

    async def embed(self, texts: list[str], task_type: llm.EmbedTaskType) -> list[list[float]]:
        s = self.settings
        keys = [_key(s.model_embed, str(s.embed_dim), task_type, t) for t in texts]
        todo = sorted({(k, t) for k, t in zip(keys, texts, strict=True) if k not in self._emb.data})
        if todo:
            result = await llm.embed([t for _, t in todo], task_type=task_type)
            self.embed_cost_new += result.cost_usd
            for (k, _), vec in zip(todo, result.vectors, strict=True):
                self._emb.put(k, [round(x, 6) for x in vec])
        return [self._emb.data[k] for k in keys]

    # ---------------------------------------------------------------- Wikipedia pages

    def wiki_get(self, label: str) -> dict[str, Any] | None:
        return self._wiki.data.get(label)

    def wiki_cached(self) -> int:
        return len(self._wiki.data)

    def wiki_put(self, label: str, value: dict[str, Any]) -> None:
        self._wiki.put(label, value)
