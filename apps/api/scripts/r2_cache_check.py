"""Decision 65 R2 check: one-word concepts the policy/politics neighbour rule newly names in
cached results (searches of the last 3 days and the outlet lists). Read only.

    uv run python -m scripts.r2_cache_check        # after `make check-gcp`
"""

import asyncio
from datetime import UTC, datetime, timedelta

TOPICS = ("policy", "politics")


def newly_named(g, text: str, topic: str) -> list:  # type: ignore[no-untyped-def]
    from app.recs import feed_rank as fr

    full = fr.DOMAIN_GROUPS
    try:
        a = {c.id: c for c in fr.named_concepts(g, text, topic)}
        fr.DOMAIN_GROUPS = full[:1]  # decision 64's rule: the business group only
        b = {c.id for c in fr.named_concepts(g, text, topic)}
    finally:
        fr.DOMAIN_GROUPS = full
    return [a[cid] for cid in a.keys() - b]


async def main() -> int:
    from app.config import get_settings
    from app.graph.loader import get_graph, load_serving_graph
    from app.recs.models import WebResult
    from app.store.docstore import get_doc_store

    await load_serving_graph(get_settings().concepts_uri)
    g, s, now = get_graph(), get_doc_store(), datetime.now(UTC)
    days = [(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(3)]
    rows, found = 0, []

    def check(where: str, raw: dict, topic: str) -> None:  # type: ignore[type-arg]
        nonlocal rows
        r = WebResult.model_validate(raw)
        rows += 1
        for c in newly_named(g, f"{r.title} {r.snippet}", topic):
            found.append(f"{topic}/{where}: {c.label} [{c.domain}] in {r.title[:60]!r}")

    for topic in TOPICS:
        for day in days:
            for key, fmts in ((f"feed:{topic}:{day}", ("video", "podcast")),
                              (f"feedx:{topic}:{day}", ("article",))):  # fmt: skip
                for f in fmts:
                    for raw in (await s.get(f"rec_cache/{key}__{f}") or {}).get("results", []):
                        check(f, raw, topic)
        for outlet, v in (await s.get(f"rec_cache/outlets:{topic}") or {}).items():
            for raw in v.get("items", []) if isinstance(v, dict) else []:
                check(f"outlet {outlet}", raw, topic)
    print(f"R2 check over cached policy/politics results (searches {days[-1]}..{days[0]} and "
          f"outlet lists): {rows} rows, {len(found)} newly named")  # fmt: skip
    for line in found:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
