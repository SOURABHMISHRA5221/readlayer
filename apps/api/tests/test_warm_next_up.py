"""Decision 67 N4: what warm_next_up would search, and the provider call counts."""

from scripts import warm_next_up as w
from tests.test_recs_library import DOCS, GRAPH


async def test_plans_each_key_idea_and_format_once_and_skips_fresh_entries():
    docs = {d.content_id: d for d in DOCS}
    asked = []

    async def cached(concept_id, fmt, query):
        asked.append((concept_id, fmt))
        return fmt == "video"  # video entries are fresh

    misses = await w.plan_misses(docs, GRAPH, {"article", "video", "podcast"}, cached)
    assert len(asked) == len(set(asked))  # a shared concept is looked up once
    assert misses and all(m.fmt != "video" for m in misses)
    calls = w.provider_calls(misses)
    assert calls == {"tavily": len(misses), "youtube": 0}


def test_youtube_counts_two_calls():
    m = w.Miss("c", "k", "Label", "finance", "video")
    assert w.provider_calls([m, m]) == {"tavily": 0, "youtube": 4}
