"""One topic matcher for every box where a reader names a subject (decisions 42, 48): onboarding's
free text, learning goals and Describe yourself.

`match_topic` takes one redacted phrase: whole-phrase alias → words and 2-word chunks against the
aliases and concept labels (`word_topic`, no model call) → the nearest topic scope line by
embedding (this phrase alone in its request, cosine ≥ ONBOARDING_TOPIC_THRESHOLD). The pure
parts live in `app/reader/onboarding_text.py`; this module adds the embedding (I/O). Callers
that check the alias earlier in their own order (onboarding, goals) run it again here: it is a
dict lookup, free, and keeps one order in one place.
"""

from dataclasses import dataclass

from app import llm
from app.config import Settings
from app.graph.graph import ConceptGraph
from app.reader import onboarding_text as ot

_topic_vectors: tuple[str, list[list[float]]] | None = None


async def topic_vectors(settings: Settings) -> list[list[float]]:
    """The 14 topics' label + scope embeddings, once per process (and embedding model)."""
    global _topic_vectors
    key = f"{settings.model_embed}|{settings.embed_dim}"
    if _topic_vectors is None or _topic_vectors[0] != key:
        result = await llm.embed(ot.topic_texts(), task_type="SEMANTIC_SIMILARITY")
        _topic_vectors = (key, result.vectors)
    return _topic_vectors[1]


def reset_topic_vectors() -> None:
    global _topic_vectors
    _topic_vectors = None


class Embedder:
    """Embeds each phrase at most once per request (resolve_names and the topic fallback share
    the vectors) and adds up the cost. Callers pass one phrase per call (privacy rule)."""

    def __init__(self) -> None:
        self.vectors: dict[str, list[float]] = {}
        self.cost = 0.0
        self.calls = 0

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        new = list(dict.fromkeys(t for t in texts if t not in self.vectors))
        if new:
            result = await llm.embed(new, task_type="SEMANTIC_SIMILARITY")
            self.calls += 1
            self.cost += result.cost_usd
            self.vectors.update(zip(new, result.vectors, strict=True))
        return [self.vectors[t] for t in texts]


@dataclass(frozen=True)
class TopicMatch:
    topic: str
    via: str  # "alias" | "words" | "embedding"


async def match_topic(
    graph: ConceptGraph, phrase: str, embedder: Embedder, settings: Settings
) -> TopicMatch | None:
    if (topic := ot.alias_topic(phrase)) is not None:
        return TopicMatch(topic, "alias")
    if (words := ot.word_topic(graph, phrase)) is not None:
        return TopicMatch(words.topic, "words")
    return await embedding_topic(phrase, embedder, settings)


async def embedding_topic(phrase: str, embedder: Embedder, settings: Settings) -> TopicMatch | None:
    """The phrase alone in its embed request; an outage means no match."""
    try:
        scopes = await topic_vectors(settings)
        (vector,) = await embedder([phrase])
    except llm.LLMError:
        return None
    near = ot.nearest_topic(vector, scopes, settings.onboarding_topic_threshold)
    return TopicMatch(near[0], "embedding") if near else None
