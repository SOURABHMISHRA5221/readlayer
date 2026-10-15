"""For you row quality, before and after decision 64 (plan docs/plans/feed-quality.md). Read only.

    uv run python -m scripts.feed_quality            # after `make check-gcp`

For each demo persona: the stored feed (`persona_feeds/{p}`) and template, ranked and selected in
memory as GET /v1/feed does for a fresh demo reader; per first-page row the named concepts,
readiness and read-first line. Then, per persona topic, how many cached search results of the
last 3 days (`rec_cache` `feed:`/`feedx:` entries) pass `feed.keep_for`, and how many snapshot
items would fail `is_relevant`. Runs against whichever code it sits in: copy it into a worktree
of `main` for decision 64's "before" numbers (named_concepts took no topic there). Decision 65:
stored articles carry their key ideas; `--title-only` turns that and the policy/politics
neighbours off (the "before" for decision 65). Writes nothing.
"""

import argparse
import asyncio
import inspect
from collections import Counter
from datetime import UTC, datetime, timedelta

JUNK = ("c_take_a_touch", "c_give_the_treatment", "c_activity_theory")
PERSONAS = ("newcomer", "trader", "policy_student")
DAYS = 3


def namer(fr):
    takes_topic = len(inspect.signature(fr.named_concepts).parameters) == 3
    return lambda graph, text, topic: (
        fr.named_concepts(graph, text, topic) if takes_topic else fr.named_concepts(graph, text)
    )


def single_word(concept) -> bool:
    return " " not in concept.label.strip() or "(" in concept.label


async def first_pages(graph, store, now, named, library) -> None:
    from app.recs import feed_rank as fr
    from app.recs.feed import PERSONA_COUNTRY, SnapshotRepo, side_for
    from app.recs.outlets import LOCAL_SHARE
    from app.recs.rank import PERSONA_FORMAT_PRIORS
    from app.store.persona_repo import get_template
    from app.store.reader_repo import state_from_demo

    totals: Counter[str] = Counter()
    singles: list[str] = []
    for persona in PERSONAS:
        doc = await get_template(store, persona)
        snap = await SnapshotRepo(store).get(persona)
        if snap is None:
            print(f"{persona}: no stored feed")
            continue
        cands = [
            fr.FeedCandidate(r, topic, named(graph, f"{r.title} {r.snippet}", topic))
            for topic, r in snap.items
        ]
        reader = fr.FeedReader(
            state=state_from_demo("feed-quality", persona, doc, False),
            interest=dict.fromkeys(snap.topics, 1.0),
            prior=PERSONA_FORMAT_PRIORS[persona],
        )
        if library is not None:
            cands = fr.attach_ideas(cands, library, graph)
        rows = fr.select(fr.rank(cands, reader, now, graph), list(snap.topics),
                         side_for(PERSONA_COUNTRY), LOCAL_SHARE)  # fmt: skip
        print(f"\n{persona} (feed {snap.prepared_at}): {len(rows)} rows")
        for r in rows:
            c = r.candidate
            labels = [x.label for x in c.concepts]
            basis = getattr(r, "readiness_basis", "title")[0]
            level = r.readiness or "-"
            print(f"  {c.result.format:7} {c.topic:10} {level:8} {basis} {c.result.title[:60]!r}")
            print(f"      url={c.result.url}")
            if getattr(c, "ideas", None):
                print(f"      ideas={[x.label for x in c.ideas]}")
            print(f"      named={labels} read_first={list(r.read_first)}")
            totals["rows"] += 1
            totals["junk rows"] += any(x.id in JUNK for x in c.concepts)
            totals["read-first rows"] += bool(r.read_first)
            totals[f"{persona} {r.readiness or 'none'}"] += 1
            singles += [f"{persona}/{c.topic}: {x.label} [{x.domain}] in {c.result.title[:50]!r}"
                        for x in c.concepts if single_word(x)]  # fmt: skip
    print(f"\nfirst pages: {dict(totals)}")
    print(f"single-word concepts named on first pages ({len(singles)}):")
    for line in singles:
        print(f"  {line}")


async def relevance(graph, store, now, named) -> None:
    from app.recs import feed_rank as fr
    from app.recs.feed import PERSONA_TOPICS, SnapshotRepo, keep_for

    topics = sorted({t for ts in PERSONA_TOPICS.values() for t in ts})
    days = [(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(DAYS)]
    print(f"\ncached search results passing keep_for, days {days[-1]}..{days[0]}:")
    for topic in topics:
        keep = keep_for(topic, graph, now)
        counts: Counter[str] = Counter()
        for day in days:
            for stem, fmts in (("feed", ("video", "podcast")), ("feedx", ("article",))):
                for fmt in fmts:
                    doc = await store.get(f"rec_cache/{stem}:{topic}:{day}__{fmt}")
                    for raw in (doc or {}).get("results", []):
                        counts[f"{fmt} seen"] += 1
                        counts[f"{fmt} kept"] += keep(fr.WebResult.model_validate(raw))
        print(f"  {topic:11} {dict(sorted(counts.items()))}")
    for persona in PERSONAS:
        snap = await SnapshotRepo(store).get(persona)
        if snap is None:
            continue
        failing = [
            f"{t}/{r.format}: {r.title[:50]!r}"
            for t, r in snap.items
            if r.format != "article"  # outlet articles skip the topic check (section = topic)
            and not fr.is_relevant(r, t, named(graph, f"{r.title} {r.snippet}", t))
        ]
        print(f"  {persona}: {len(failing)} snapshot videos/podcasts now fail is_relevant")
        for line in failing:
            print(f"    {line}")


def dropped_aliases(graph) -> None:
    try:
        from app.graph.graph import ALIAS_STOPWORDS
    except ImportError:
        print("\nalias stopwords: not in this code")
        return
    from app.graph.build import normalize_label

    print("\naliases F1 leaves out of the index (alias, concept, domain):")
    for c in graph.concepts:
        for a in c.aliases:
            if normalize_label(a) in ALIAS_STOPWORDS:
                print(f"  {a!r} → {c.label} [{c.domain}]")


async def main(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.graph.loader import get_graph, load_serving_graph
    from app.recs import feed_rank as fr
    from app.store.docstore import get_doc_store

    settings = get_settings()
    print(f"project {settings.db_project}")
    await load_serving_graph(settings.concepts_uri)
    graph, now, store = get_graph(), datetime.now(UTC), get_doc_store()
    print(f"served graph {graph.version}, {len(graph)} concepts")
    named = namer(fr)
    library = None
    if hasattr(fr, "attach_ideas"):
        if args.title_only:
            fr.DOMAIN_GROUPS = fr.DOMAIN_GROUPS[:1]  # decision 64's rule: business group only
        else:
            from app.content import catalog

            library = {d.content_id: d for d in await catalog.all_docs()}
    print(f"mode: {'title only' if library is None else 'stored articles use key ideas'}")
    await first_pages(graph, store, now, named, library)
    await relevance(graph, store, now, named)
    dropped_aliases(graph)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--title-only", action="store_true", help="decision 64's rule (no ideas)")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
