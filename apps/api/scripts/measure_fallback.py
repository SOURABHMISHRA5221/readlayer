"""Decision 50 §D: does the restricted search fallback return enough? Local, no LLM, no write.

    cd apps/api && uv run python -m scripts.measure_fallback [--write]

Per topic ("<Label> news this week") and per sample concept ("<label> news this week"), one
Tavily article search without and one with `include_domains` = FALLBACK_DOMAINS, counted after
the live keep filters (page shape, 14-day date, topic or concept relevance). 2 × (14 + 4) = 36
Tavily credits; results aren't cached or counted in ops/search. Rule fixed in the plan: if the
restricted search returns < 2 articles for most topics, the fallback is dropped.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.graph.loader import load_graph
from app.graph.taxonomy import DOMAIN_IDS
from app.recs.feed import FALLBACK_DOMAINS, concept_query, feed_query, keep_for, keep_for_concept
from app.recs.web_search import TavilyProvider, load_blocklist

OUT = Path(__file__).resolve().parents[3] / "docs" / "evidence" / "d50" / "fallback.txt"
CONCEPTS = ("Repo rate", "Offside", "Large language model", "Inflation")


async def count(tavily, query, keep, domains):
    try:
        results = await tavily.search(query, "article", news=True, include_domains=domains)
    except Exception as exc:  # recorded, not fatal
        return f"error {type(exc).__name__}", []
    kept = [r for r in results if keep(r)]
    return f"{len(kept)}/{len(results)}", kept


async def main(args) -> int:
    settings = get_settings()
    graph = await load_graph(settings.concepts_uri)
    tavily = TavilyProvider(settings.tavily_api_key.get_secret_value(), load_blocklist(),
                            settings.search_timeout_s)  # fmt: skip
    now = datetime.now(UTC)
    lines = [
        f"# Decision 50 fallback measurement, {now.isoformat(timespec='minutes')}",
        "# kept/returned after the live keep filters; 'restricted' = include_domains",
        "",
    ]
    restricted_ok = 0
    for topic in DOMAIN_IDS:
        q = feed_query(topic, "article")
        keep = keep_for(topic, graph, now)
        plain, _ = await count(tavily, q, keep, ())
        rest, kept = await count(tavily, q, keep, FALLBACK_DOMAINS)
        restricted_ok += sum(1 for _ in kept) >= 2
        hosts = sorted({r.source for r in kept})
        lines.append(f"topic   {topic:12} plain {plain:>6}  restricted {rest:>6}  {hosts}")
    lines.append("")
    for label in CONCEPTS:
        concept = graph.lookup(label)
        if concept is None:
            lines.append(f"concept {label}: not in the graph")
            continue
        q, keep = concept_query(concept), keep_for_concept(concept, now)
        plain, _ = await count(tavily, q, keep, ())
        rest, kept = await count(tavily, q, keep, FALLBACK_DOMAINS)
        lines.append(f"concept {concept.label:24} plain {plain:>6}  restricted {rest:>6}  "
                     f"{sorted({r.source for r in kept})}")  # fmt: skip
    verdict = "keep" if restricted_ok * 2 > len(DOMAIN_IDS) else "DROP (plan rule)"
    lines += [
        "",
        f"topics with ≥ 2 restricted articles: {restricted_ok}/{len(DOMAIN_IDS)} → {verdict}",
    ]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.write:
        OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
